"""Admin configuration management page."""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates

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
    # TODO: Pull real config from ConfigService.
    config_summary = redact_dict({
        "ma_base_url": "",
        "ma_token": "",
        "public_base_url": "",
        "stream_base_url": "",
        "locale": "en-US",
        "aws_default_region": "us-east-1",
        "log_level": "info",
        "debug": False,
    })

    return templates.TemplateResponse(
        request,
        "config.html",
        {
            "base_path": get_ingress_base_path(request),
            "config": config_summary,
        },
    )


@router.post("/update")
async def update_config(request: Request) -> JSONResponse:
    """Update non-sensitive config values.

    Sensitive values (tokens, passwords) use a separate replacement flow
    where the new value is accepted but never re-displayed.

    TODO: Persist updates via ConfigService.
    """
    try:
        body: dict[str, Any] = await request.json()
        logger.info("Config update requested for keys: %s", list(body.keys()))
        return JSONResponse(content={
            "success": True,
            "message": "Config update is not yet implemented.",
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

    TODO: Validate the new token against MA before persisting.
    """
    try:
        body = await request.json()
        new_token = body.get("ma_token", "")
        if not new_token:
            return JSONResponse(
                content={"success": False, "message": "No token provided."},
                status_code=400,
            )
        logger.info("Token replacement requested.")
        # TODO: Validate + persist.
        return JSONResponse(content={
            "success": True,
            "message": "Token replacement is not yet implemented.",
        })
    except Exception as exc:
        logger.exception("Error replacing token.")
        return JSONResponse(
            content={"success": False, "message": str(exc)},
            status_code=400,
        )
