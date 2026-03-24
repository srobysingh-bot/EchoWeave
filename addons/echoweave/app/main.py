"""EchoWeave — FastAPI application entry point.

Creates the app, registers routers, mounts static/template directories,
and defines startup/shutdown lifecycle events.
"""

from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager
from typing import AsyncGenerator

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

from app.core.constants import APP_DESCRIPTION, APP_NAME, APP_VERSION
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
from app.alexa.router import router as alexa_router

logger = logging.getLogger(__name__)


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

    logger.info("%s v%s starting up.", APP_NAME, APP_VERSION)

    # Persistence
    from app.storage.persistence import PersistenceService
    persistence = PersistenceService(settings.data_dir)
    registry.register("persistence", persistence)

    # MA client
    from app.ma.client import MusicAssistantClient
    ma_client = MusicAssistantClient(
        base_url=settings.ma_base_url,
        token=settings.ma_token,
    )
    registry.register("ma_client", ma_client)

    # Session store
    from app.alexa.session_store import init_session_store
    session_store = init_session_store(persistence=persistence)
    registry.register("session_store", session_store)

    # Health service
    from app.diagnostics.health import HealthService
    health_svc = HealthService()
    registry.register("health", health_svc)

    # Config service
    from app.core.config_service import ConfigService
    config_svc = ConfigService(settings, persistence)
    registry.register("config_service", config_svc)

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
    _app = FastAPI(
        title=APP_NAME,
        description=APP_DESCRIPTION,
        version=APP_VERSION,
        docs_url="/docs" if os.getenv("ECHOWEAVE_DEBUG", "").lower() == "true" else None,
        redoc_url=None,
        lifespan=lifespan,
    )

    # Register routers
    _app.include_router(health_router)
    _app.include_router(status_router)
    _app.include_router(setup_router)
    _app.include_router(logs_router)
    _app.include_router(config_router)
    _app.include_router(alexa_router)

    # Static files
    _app.mount("/static", StaticFiles(directory="app/web/static"), name="static")

    # Root redirect
    @_app.get("/")
    async def root():
        return RedirectResponse(url="/status")

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
