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
    """Render the status dashboard with live health indicators."""
    from app.dependencies import get_health_service
    health_svc = get_health_service()

    items: list[dict[str, Any]] = [
        {"label": "Add-on Service", "status": "ok", "detail": f"v{APP_VERSION} running"}
    ]

    if health_svc:
        result = await health_svc.run_all()
        
        # Display name mapping
        key_map = {
            "ma_reachable": "Music Assistant Connection",
            "ma_auth_valid": "Music Assistant Auth",
            "stream_url_valid": "Stream Endpoint",
            "public_url_reachable": "Public Endpoint",
            "ask_configured": "ASK Credentials",
            "skill_exists": "Alexa Skill",
        }
        
        for c in result.checks:
            items.append({
                "label": key_map.get(c.key, c.key),
                "status": c.status,
                "detail": c.message
            })

    # Find failures for top alert UI
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
