"""Admin configuration management page."""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates

from app.core.constants import APP_VERSION
from app.core.service_registry import registry
from app.settings import Settings
from app.storage.secrets import redact_dict
from app.web.ingress import get_ingress_base_path

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/config", tags=["config"])
templates = Jinja2Templates(directory="app/web/templates")


@router.get("", response_class=HTMLResponse)
@router.get("/", response_class=HTMLResponse)
async def config_page(request: Request) -> HTMLResponse:
    """Render the configuration summary page.

    Shows current config with secrets redacted.  Provides a form to
    update safe (non-sensitive) settings.
    """
    config_svc = registry.get_optional("config_service")
    if config_svc:
        settings = config_svc.settings
    else:
        settings = Settings()

    settings_dict = settings.model_dump() if hasattr(settings, "model_dump") else dict(vars(settings))

    config_summary = redact_dict({
        "ma_base_url": settings_dict.get("ma_base_url", ""),
        "ma_token": settings_dict.get("ma_token", ""),
        "public_base_url": settings_dict.get("public_base_url", ""),
        "stream_base_url": settings_dict.get("stream_base_url", ""),
        "locale": settings_dict.get("locale", "en-US"),
        "aws_default_region": settings_dict.get("aws_default_region", "us-east-1"),
        "log_level": settings_dict.get("log_level", "info"),
        "debug": bool(settings_dict.get("debug", False)),
    })

    if settings_dict.get("ma_token"):
        config_summary["ma_token"] = "**** (set)"

    return templates.TemplateResponse(
        request,
        "config.html",
        {
            "base_path": get_ingress_base_path(request),
            "version": APP_VERSION,
            "config": config_summary,
        },
    )


@router.post("/update")
async def update_config(request: Request) -> JSONResponse:
    """Update non-sensitive config values.

    Sensitive values (tokens, passwords) use a separate replacement flow
    where the new value is accepted but never re-displayed.

    Persists updates via ConfigService.
    """
    try:
        body: dict[str, Any] = await request.json()

        config_svc = registry.get_optional("config_service")
        if not config_svc:
            return JSONResponse(
                content={"success": False, "message": "Config service not available."},
                status_code=503,
            )

        config_svc.save_updates(body)
        logger.info("Config update persisted for keys: %s", list(body.keys()))
        return JSONResponse(content={
            "success": True,
            "message": "Configuration updated.",
        })
    except Exception as exc:
        logger.exception("Error updating config.")
        return JSONResponse(
            content={"success": False, "message": str(exc)},
            status_code=400,
        )


@router.post("/replace-token")
async def replace_token(request: Request) -> JSONResponse:
    """Replace the Music Assistant token.

    The new token is accepted and persisted but never echoed back.

    Token is persisted to ConfigService and storage.
    """
    try:
        body = await request.json()
        new_token = body.get("ma_token", "")
        if not new_token:
            return JSONResponse(
                content={"success": False, "message": "No token provided."},
                status_code=400,
            )

        config_svc = registry.get_optional("config_service")
        if not config_svc:
            return JSONResponse(
                content={"success": False, "message": "Config service not available."},
                status_code=503,
            )

        config_svc.save_updates({"ma_token": new_token})
        logger.info("Token replacement persisted.")
        return JSONResponse(content={
            "success": True,
            "message": "Token updated.",
        })
    except Exception as exc:
        logger.exception("Error replacing token.")
        return JSONResponse(
            content={"success": False, "message": str(exc)},
            status_code=400,
        )
