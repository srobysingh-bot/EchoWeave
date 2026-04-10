"""EchoWeave — FastAPI application entry point.

Creates the app, registers routers, mounts static/template directories,
and defines startup/shutdown lifecycle events.
"""

from __future__ import annotations

import logging
import os
import re
from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncGenerator

import httpx
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

from app.core.constants import (
    APP_BUILD_ID,
    APP_DESCRIPTION,
    APP_NAME,
    APP_QUERY_RESOLUTION_REV,
    APP_VERSION,
)
from app.core.exceptions import EchoWeaveError
from app.core.service_registry import registry
from app.logging_config import setup_logging
from app.settings import load_settings

# Import routers
from app.web.routes_health import router as health_router
from app.web.routes_status import router as status_router
from app.web.routes_setup import router as setup_router
from app.web.routes_logs import router as logs_router, install_log_buffer
from app.web.routes_config import router as config_router
from app.ma.router import router as ma_router
from app.web.ingress import get_ingress_base_path

logger = logging.getLogger(__name__)

APP_DIR = Path(__file__).resolve().parent
WEB_DIR = APP_DIR / "web"
STATIC_DIR = WEB_DIR / "static"


class NormalizePathASGIMiddleware:
    """Normalize repeated slashes in ASGI scope path before routing."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope.get("type") == "http":
            original_path = scope.get("path") or "/"
            normalized_path = re.sub(r"/{2,}", "/", original_path)
            if normalized_path != original_path:
                scope = dict(scope)
                scope["path"] = normalized_path
                scope["raw_path"] = normalized_path.encode("utf-8")
        await self.app(scope, receive, send)


def _serialise_routes(fastapi_app: FastAPI) -> list[dict[str, object]]:
    """Build a JSON-safe route listing for diagnostics."""
    route_rows: list[dict[str, object]] = []
    for route in fastapi_app.routes:
        methods = sorted(route.methods) if getattr(route, "methods", None) else []
        route_rows.append(
            {
                "path": route.path,
                "name": route.name,
                "methods": methods,
            }
        )
    return sorted(route_rows, key=lambda row: str(row["path"]))


# ---------------------------------------------------------------------------
# Lifespan (startup / shutdown)
# ---------------------------------------------------------------------------

@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Application lifespan: initialise services on startup, clean up on shutdown."""
    # -- startup -------------------------------------------------------------
    settings = load_settings()
    setup_logging(level=settings.log_level)
    install_log_buffer()

    build_sha = (
        os.getenv("ECHOWEAVE_GIT_SHA")
        or os.getenv("GIT_COMMIT_SHA")
        or os.getenv("SOURCE_COMMIT")
        or APP_BUILD_ID
    )
    logger.info(
        "%s v%s starting up. build_sha=%s build_id=%s query_resolution_rev=%s",
        APP_NAME,
        APP_VERSION,
        build_sha,
        APP_BUILD_ID,
        APP_QUERY_RESOLUTION_REV,
    )
    logger.info("Static directory: %s (exists=%s)", app.state.static_dir, STATIC_DIR.is_dir())
    logger.info("Template directory: %s (exists=%s)", app.state.template_dir, app.state.template_dir_exists)

    for row in _serialise_routes(app):
        logger.info("Route registered: %s methods=%s", row["path"], row["methods"])

    # Persistence
    from app.storage.persistence import PersistenceService
    persistence = PersistenceService(settings.data_dir)
    registry.register("persistence", persistence)

    # Config service resolves effective runtime settings (addon/env/persisted/default).
    from app.core.config_service import ConfigService
    config_svc = ConfigService(settings, persistence)
    config_svc.resolve_effective()
    config_svc.log_effective_runtime()
    registry.register("config_service", config_svc)

    # MA client
    from app.ma.client import MusicAssistantClient
    ma_client = MusicAssistantClient(
        base_url=settings.ma_base_url,
        token=settings.ma_token,
    )
    registry.register("ma_client", ma_client)

    # Connector mode startup (register + heartbeat)
    if settings.is_connector_mode:
        from app.connector.client import ConnectorClient
        from app.connector.command_dispatch import execute_connector_command
        from app.connector.heartbeat import HeartbeatRunner
        from app.connector.registration import register_connector

        connector_client = ConnectorClient(
            backend_url=settings.backend_url,
            connector_id=settings.connector_id,
            connector_secret=settings.connector_secret,
            tenant_id=settings.tenant_id,
            home_id=settings.home_id,
        )
        # Inject config service for bootstrap auth
        connector_client._config_service = config_svc
        registry.register("connector_client", connector_client)

        async def _command_handler(command: dict) -> tuple[bool, str, dict]:
            return await execute_connector_command(command, ma_client)

        heartbeat_runner = HeartbeatRunner(
            connector_client,
            interval_seconds=30,
            command_handler=_command_handler,
        )
        registry.register("connector_heartbeat", heartbeat_runner)

        ma_reachable = False
        try:
            ma_reachable = await ma_client.ping()
        except Exception:
            logger.exception("Failed MA ping during connector registration startup.")

        if settings.connector_configured:
            await register_connector(connector_client, ma_reachable=ma_reachable)
            await heartbeat_runner.start()
        else:
            connector_client.state.registration_message = "connector-config-missing"
            logger.warning("Connector mode enabled but connector configuration is incomplete.")

    if settings.is_edge_mode:
        from app.edge.client_ws import EdgeConnectorWSClient
        from app.edge.command_dispatch import execute_edge_command

        async def _edge_command_handler(command_type: str, payload: dict) -> dict:
            return await execute_edge_command(
                command_type,
                payload,
                ma_client,
                default_queue_id=settings.alexa_source_queue_id,
            )

        edge_client = EdgeConnectorWSClient(
            worker_base_url=settings.worker_base_url,
            connector_id=settings.connector_id,
            connector_secret=settings.connector_secret,
            tenant_id=settings.tenant_id,
            home_id=settings.home_id,
            source_queue_id=settings.alexa_source_queue_id,
            command_handler=_edge_command_handler,
        )
        registry.register("edge_connector_ws", edge_client)

        if settings.connector_configured:
            origin_base_url = settings.tunnel_base_url or settings.public_base_url or settings.stream_base_url
            register_payload = {
                "connector_id": settings.connector_id,
                "connector_secret": settings.connector_secret,
                "tenant_id": settings.tenant_id,
                "home_id": settings.home_id,
                "origin_base_url": origin_base_url,
                "alexa_source_queue_id": settings.alexa_source_queue_id,
                "capabilities": {
                    "commands": [
                        "prepare_play",
                        "resolve_stream",
                        "get_current_item",
                        "get_next_item",
                        "get_state",
                        "pause",
                        "resume",
                        "stop",
                        "next",
                        "previous",
                    ],
                    "stream_route": "/edge/stream/{queue_id}/{queue_item_id}",
                },
            }
            register_headers = {"content-type": "application/json"}
            settings_bootstrap_secret = settings.connector_bootstrap_secret or ""
            env_bootstrap_secret = os.getenv("ECHOWEAVE_CONNECTOR_BOOTSTRAP_SECRET", "")
            bootstrap_secret = settings_bootstrap_secret or env_bootstrap_secret
            bootstrap_source = "settings" if settings_bootstrap_secret else ("environment" if env_bootstrap_secret else "none")
            logger.info(
                "Edge connector registration auth: bootstrap_secret_set=%s source=%s",
                bool(bootstrap_secret),
                bootstrap_source,
            )
            if bootstrap_secret:
                register_headers["x-connector-bootstrap-secret"] = bootstrap_secret
            try:
                async with httpx.AsyncClient(timeout=10) as client:
                    resp = await client.post(
                        f"{settings.worker_base_url}/v1/connectors/register",
                        json=register_payload,
                        headers=register_headers,
                    )
                if resp.status_code != 200:
                    logger.warning(
                        "Edge connector registration failed: status=%s body=%s",
                        resp.status_code,
                        resp.text,
                    )
                    if resp.status_code == 401:
                        logger.warning(
                            "Edge connector registration unauthorized. Check connector_bootstrap_secret in add-on options against worker CONNECTOR_BOOTSTRAP_SECRET."
                        )
                else:
                    logger.info("Edge connector registration succeeded.")
            except Exception:
                logger.exception("Edge connector registration request failed.")

            await edge_client.start()
        else:
            logger.warning("Edge mode enabled but connector configuration is incomplete.")

    # Session store
    if not settings.is_edge_mode:
        from app.alexa.session_store import init_session_store

        session_store = init_session_store(persistence=persistence)
        registry.register("session_store", session_store)

    # Health service
    from app.diagnostics.health import HealthService
    from app.diagnostics.checks import check_public_url, check_ask_configured, check_skill_exists
    from app.ma.health import MAHealthChecker

    health_svc = HealthService()

    async def ma_checks():
        client = registry.get("ma_client")
        if client:
            checker = MAHealthChecker(client)
            return await checker.run_all(
                settings.stream_base_url,
                settings.allow_insecure_local_test,
                include_stream_check=not settings.is_connector_mode and not settings.is_edge_mode,
            )
        return [{"key": "ma_reachable", "status": "fail", "message": "MA client not registered."}]

    async def public_check():
        # check_public_url probes /healthz to avoid recursive /health self-check loops.
        return await check_public_url(settings.public_base_url)

    async def ask_check():
        return await check_ask_configured(settings.data_dir)

    async def skill_check():
        return await check_skill_exists(persistence)

    health_svc.register_check(ma_checks)
    if not settings.is_connector_mode and not settings.is_edge_mode:
        health_svc.register_check(public_check)
        health_svc.register_check(ask_check)
        health_svc.register_check(skill_check)

    registry.register("health", health_svc)

    logger.info("All services initialised.")

    yield

    # -- shutdown ------------------------------------------------------------
    logger.info("%s shutting down.", APP_NAME)
    await registry.shutdown()


# ---------------------------------------------------------------------------
# App factory
# ---------------------------------------------------------------------------

def create_app() -> FastAPI:
    """Build and configure the FastAPI application."""
    startup_settings = load_settings()

    _app = FastAPI(
        title=APP_NAME,
        description=APP_DESCRIPTION,
        version=APP_VERSION,
        docs_url="/docs" if os.getenv("ECHOWEAVE_DEBUG", "").lower() == "true" else None,
        redoc_url=None,
        lifespan=lifespan,
    )

    _app.state.static_dir = str(STATIC_DIR)
    _app.state.template_dir = str(WEB_DIR / "templates")
    _app.state.template_dir_exists = (WEB_DIR / "templates").is_dir()

    # Register routers
    _app.include_router(health_router)
    _app.include_router(status_router)
    _app.include_router(setup_router)
    _app.include_router(logs_router)
    _app.include_router(config_router)
    _app.include_router(ma_router)
    if startup_settings.is_edge_mode:
        from app.edge.stream_router import router as edge_stream_router

        _app.include_router(edge_stream_router)

        @_app.get("/alexa/intents", tags=["alexa"])
        @_app.get("/alexa/intents/", tags=["alexa"])
        async def edge_alexa_intents_probe() -> JSONResponse:
            """Edge-mode contract response for MA Alexa provider /alexa/intents preload."""
            payload = {
                "invocationName": "music assistant",
                "intents": [
                    {"intent": "PlayAudio", "utterances": ["play audio", "start", "play"]},
                    {"intent": "AMAZON.StopIntent", "utterances": ["stop"]},
                    {
                        "intent": "AMAZON.ResumeIntent",
                        "utterances": ["play audio", "start", "play", "resume"],
                    },
                    {"intent": "AMAZON.PauseIntent", "utterances": ["pause"]},
                    {"intent": "AMAZON.NextIntent", "utterances": ["next"]},
                    {"intent": "AMAZON.PreviousIntent", "utterances": ["previous"]},
                ],
            }
            logger.info("edge_alexa_intents_probe response payload=%s", payload)
            return JSONResponse(content=payload, status_code=200)
    else:
        from app.alexa.router import router as alexa_router

        _app.include_router(alexa_router)

    # Static files
    _app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

    @_app.middleware("http")
    async def request_trace_middleware(request: Request, call_next):
        logger.info(
            "HTTP request received: method=%s path=%s raw_path=%s root_path=%s x_ingress_path=%s",
            request.method,
            request.url.path,
            request.scope.get("raw_path", b"").decode("utf-8", errors="ignore"),
            request.scope.get("root_path", ""),
            request.headers.get("X-Ingress-Path", ""),
        )
        response = await call_next(request)
        logger.info(
            "HTTP response sent: method=%s path=%s status=%s matched=%s effective_base=%s",
            request.method,
            request.url.path,
            response.status_code,
            response.status_code != 404,
            get_ingress_base_path(request),
        )
        return response

    # Basic Auth Middleware
    import base64
    import secrets
    from fastapi.responses import Response
    from starlette.middleware.base import BaseHTTPMiddleware

    class AdminAuthMiddleware(BaseHTTPMiddleware):
        async def dispatch(self, request: Request, call_next):
            # Exempt paths
            if request.url.path.startswith(("/alexa", "/edge", "/health", "/static", "/debug", "/ma/push-url")) or \
               "/debug/" in request.url.path:
                return await call_next(request)

            # Home Assistant ingress already authenticates users.
            if request.headers.get("X-Ingress-Path") or request.scope.get("root_path"):
                return await call_next(request)
            
            # Fetch current settings from registry
            config_svc = registry.get_optional("config_service")
            if not config_svc or not config_svc.settings.ui_auth_enabled:
                return await call_next(request)
                
            settings = config_svc.settings
            auth_header = request.headers.get("Authorization")
            if auth_header and auth_header.startswith("Basic "):
                try:
                    decoded = base64.b64decode(auth_header[6:]).decode("utf-8")
                    username, _, password = decoded.partition(":")
                    if secrets.compare_digest(username, settings.ui_username) and \
                       secrets.compare_digest(password, settings.ui_password):
                        return await call_next(request)
                except Exception:
                    pass

            logger.info(
                "AdminAuthMiddleware denied request: method=%s path=%s has_auth_header=%s",
                request.method,
                request.url.path,
                bool(auth_header),
            )
                    
            return Response(
                content="Unauthorized", 
                status_code=401, 
                headers={"WWW-Authenticate": 'Basic realm="EchoWeave Admin"'}
            )

    _app.add_middleware(AdminAuthMiddleware)
    _app.add_middleware(NormalizePathASGIMiddleware)

    # Root redirect
    @_app.get("/", include_in_schema=False)
    async def root(request: Request):
        return RedirectResponse(url="setup")

    @_app.get("//", include_in_schema=False)
    async def root_emergency_compat_redirect(request: Request):
        return RedirectResponse(url="setup")

    @_app.get("/debug/routes", include_in_schema=False)
    async def debug_routes(request: Request) -> JSONResponse:
        raw_path = request.scope.get("raw_path", b"")
        if isinstance(raw_path, bytes):
            scope_raw_path = raw_path.decode("utf-8", errors="ignore")
        else:
            scope_raw_path = str(raw_path)
        return JSONResponse(
            content={
                "version": APP_VERSION,
                "scope_path": request.scope.get("path", ""),
                "scope_raw_path": scope_raw_path,
                "scope_root_path": request.scope.get("root_path", ""),
                "request_url_path": request.url.path,
                "x_ingress_path": request.headers.get("X-Ingress-Path", ""),
                "effective_base_path": get_ingress_base_path(request),
                "routes": _serialise_routes(_app),
            }
        )

    @_app.get("/debug/ping-ui", include_in_schema=False)
    async def debug_ping_ui() -> HTMLResponse:
        return HTMLResponse("<h1>EchoWeave UI OK</h1>")

    # Global exception handler
    @_app.exception_handler(EchoWeaveError)
    async def echoweave_error_handler(request: Request, exc: EchoWeaveError):
        logger.error("EchoWeaveError: %s (detail: %s)", exc, exc.detail)
        return JSONResponse(
            status_code=500,
            content={"error": str(exc), "detail": exc.detail},
        )

    @_app.exception_handler(Exception)
    async def generic_error_handler(request: Request, exc: Exception):
        logger.exception("Unhandled exception on %s %s", request.method, request.url.path)
        return JSONResponse(
            status_code=500,
            content={"error": "Internal server error."},
        )

    return _app


app = create_app()
