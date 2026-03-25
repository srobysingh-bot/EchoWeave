"""Human-friendly status dashboard."""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from app.core.constants import APP_VERSION
from app.web.ingress import get_ingress_base_path

logger = logging.getLogger(__name__)
router = APIRouter(tags=["status"])
templates = Jinja2Templates(directory="app/web/templates")


@router.get("/status", response_class=HTMLResponse)
async def status_page(request: Request) -> HTMLResponse:
    """Render the status dashboard with live health indicators."""
    from app.dependencies import get_health_service
    from app.core.service_registry import registry

    health_svc = get_health_service()
    config_svc = registry.get_optional("config_service")

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

    diagnostics = {
        "public_base_url": {"value": "", "source": "default"},
        "stream_base_url": {"value": "", "source": "default"},
        "public_probe_path": {"value": "/healthz", "source": "runtime"},
    }
    if config_svc:
        with_sources = config_svc.get_effective_with_sources()
        diagnostics["public_base_url"] = with_sources.get("public_base_url", diagnostics["public_base_url"])
        diagnostics["stream_base_url"] = with_sources.get("stream_base_url", diagnostics["stream_base_url"])

    return templates.TemplateResponse(
        request,
        "status.html",
        {
            "base_path": get_ingress_base_path(request),
            "items": items,
            "errors": errors,
            "diagnostics": diagnostics,
            "version": APP_VERSION,
            "timestamp": datetime.utcnow().isoformat() + "Z",
        },
    )
