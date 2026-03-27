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
        "mode": {"value": "legacy", "source": "default"},
        "backend_url": {"value": "", "source": "default"},
        "connector_id": {"value": "", "source": "default"},
        "tenant_id": {"value": "", "source": "default"},
        "home_id": {"value": "", "source": "default"},
        "public_base_url": {"value": "", "source": "default"},
        "stream_base_url": {"value": "", "source": "default"},
        "public_probe_path": {"value": "/healthz", "source": "runtime"},
    }
    connector_runtime = {
        "registered": "false",
        "registration_message": "not-started",
        "last_heartbeat_status": "never",
        "last_heartbeat_at": "",
    }

    if config_svc:
        with_sources = config_svc.get_effective_with_sources()
        diagnostics["mode"] = with_sources.get("mode", diagnostics["mode"])
        diagnostics["backend_url"] = with_sources.get("backend_url", diagnostics["backend_url"])
        diagnostics["connector_id"] = with_sources.get("connector_id", diagnostics["connector_id"])
        diagnostics["tenant_id"] = with_sources.get("tenant_id", diagnostics["tenant_id"])
        diagnostics["home_id"] = with_sources.get("home_id", diagnostics["home_id"])
        diagnostics["public_base_url"] = with_sources.get("public_base_url", diagnostics["public_base_url"])
        diagnostics["stream_base_url"] = with_sources.get("stream_base_url", diagnostics["stream_base_url"])

    connector_client = registry.get_optional("connector_client")
    connector_heartbeat = registry.get_optional("connector_heartbeat")
    if connector_client:
        connector_runtime = {
            "registered": str(connector_client.state.registered).lower(),
            "registration_message": connector_client.state.registration_message,
            "last_heartbeat_status": connector_client.state.last_heartbeat_status,
            "last_heartbeat_at": connector_client.state.last_heartbeat_at,
        }
    elif connector_heartbeat and hasattr(connector_heartbeat, "snapshot"):
        connector_runtime = connector_heartbeat.snapshot()

    items.append({
        "label": "Connector Registration",
        "status": "ok" if connector_runtime["registered"] == "true" else "warn",
        "detail": connector_runtime["registration_message"],
    })
    items.append({
        "label": "Connector Heartbeat",
        "status": "ok" if connector_runtime["last_heartbeat_status"] == "online" else "warn",
        "detail": connector_runtime["last_heartbeat_status"],
    })

    return templates.TemplateResponse(
        request,
        "status.html",
        {
            "base_path": get_ingress_base_path(request),
            "items": items,
            "errors": errors,
            "diagnostics": diagnostics,
            "connector_runtime": connector_runtime,
            "version": APP_VERSION,
            "timestamp": datetime.utcnow().isoformat() + "Z",
        },
    )
