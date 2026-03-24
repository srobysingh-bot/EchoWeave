"""Human-friendly status dashboard."""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from app.core.constants import APP_VERSION

logger = logging.getLogger(__name__)
router = APIRouter(tags=["status"])
templates = Jinja2Templates(directory="app/web/templates")


@router.get("/status", response_class=HTMLResponse)
async def status_page(request: Request) -> HTMLResponse:
    """Render the status dashboard with green/yellow/red indicators."""

    # Build status items — currently static; will be replaced with live
    # checks once the service registry and diagnostics layer are wired up.
    items: list[dict[str, Any]] = [
        {"label": "Add-on Service", "status": "ok", "detail": f"v{APP_VERSION} running"},
        {"label": "Music Assistant Connection", "status": "unknown", "detail": "Not checked yet"},
        {"label": "Music Assistant Auth", "status": "unknown", "detail": "Not checked yet"},
        {"label": "Public Endpoint", "status": "unknown", "detail": "Not configured"},
        {"label": "Stream Endpoint", "status": "unknown", "detail": "Not configured"},
        {"label": "Alexa Skill", "status": "unknown", "detail": "Not configured"},
        {"label": "Locale / Region", "status": "ok", "detail": "en-US"},
        {"label": "Last Alexa Callback", "status": "unknown", "detail": "None received"},
        {"label": "Last Stream Resolution", "status": "unknown", "detail": "None attempted"},
    ]

    errors: list[str] = [
        item["detail"] for item in items if item["status"] == "fail"
    ]

    return templates.TemplateResponse(
        request,
        "status.html",
        {
            "items": items,
            "errors": errors,
            "version": APP_VERSION,
            "timestamp": datetime.utcnow().isoformat() + "Z",
        },
    )
