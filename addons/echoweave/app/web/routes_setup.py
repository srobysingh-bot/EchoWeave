"""Setup wizard page — guides users through initial configuration."""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Request, Depends
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel

from app.dependencies import get_persistence, get_settings
from app.storage.models import PersistedConfig
from app.ma.client import MusicAssistantClient
from app.diagnostics.checks import check_public_url
from app.core.service_registry import registry
from app.web.ingress import get_ingress_base_path

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/setup", tags=["setup"])
templates = Jinja2Templates(directory="app/web/templates")


def _build_checklist(settings: Any, persistence: Any) -> list[dict[str, Any]]:
    """Build the setup checklist with real completion status."""
    has_ma = settings.ma_configured
    has_public = settings.public_configured
    
    # Check if ASK credentials exist
    from pathlib import Path
    ask_dir = Path(settings.data_dir) / "ask"
    has_ask = ask_dir.is_dir() and any(ask_dir.iterdir())
    
    # Check if Skill ID stored
    meta = persistence.load_skill_metadata() if persistence else None
    has_skill = bool(meta and meta.skill_id)

    return [
        {"step": 1, "label": "Music Assistant Reachable", "done": has_ma, "detail": "Configure MA URL"},
        {"step": 2, "label": "Music Assistant Token", "done": bool(settings.ma_token), "detail": "Provide long-lived token"},
        {"step": 3, "label": "Public URL Configured", "done": has_public, "detail": "Set public_base_url"},
        {"step": 4, "label": "Stream Endpoint Configured", "done": settings.stream_configured, "detail": "HTTPS stream endpoint"},
        {"step": 5, "label": "ASK Credentials Present", "done": has_ask, "detail": "Configure AWS credentials"},
        {"step": 6, "label": "Alexa Skill Created", "done": has_skill, "detail": "Create or link skill"},
    ]


@router.get("", response_class=HTMLResponse)
@router.get("/", response_class=HTMLResponse)
async def setup_page(request: Request, settings=Depends(get_settings), persistence=Depends(get_persistence)) -> HTMLResponse:
    """Render the setup wizard."""
    checklist = _build_checklist(settings, persistence)
    complete = sum(1 for item in checklist if item["done"])
    total = len(checklist)

    # Convert settings to dict for template
    settings_dict = settings.model_dump()

    return templates.TemplateResponse(
        request,
        "setup.html",
        {
            "base_path": get_ingress_base_path(request),
            "checklist": checklist,
            "complete": complete,
            "total": total,
            "progress_pct": int(complete / total * 100) if total else 0,
            "settings": settings_dict,
        },
    )


class ValidateMARequest(BaseModel):
    ma_base_url: str
    ma_token: str

@router.post("/validate-ma")
async def validate_ma(payload: ValidateMARequest) -> JSONResponse:
    """Validate Music Assistant connectivity."""
    logger.info("Validate MA requested.")
    if not payload.ma_base_url or not payload.ma_token:
        return JSONResponse({"success": False, "message": "URL and token are required."})
        
    try:
        client = MusicAssistantClient(base_url=payload.ma_base_url, token=payload.ma_token)
        is_up = await client.ping()
        if not is_up:
            return JSONResponse({"success": False, "message": "Server unreachable or responded with error."})
            
        is_valid = await client.validate_token()
        await client.close()
        
        if not is_valid:
            return JSONResponse({"success": False, "message": "Token invalid or not authorized."})
            
        return JSONResponse({"success": True, "message": "Connection and token are valid!"})
    except Exception as exc:
        logger.exception("MA Validation error")
        return JSONResponse({"success": False, "message": f"Error: {exc}"})


class ValidatePublicRequest(BaseModel):
    public_base_url: str

@router.post("/validate-public")
async def validate_public(payload: ValidatePublicRequest) -> JSONResponse:
    """Validate public endpoint reachability."""
    logger.info("Validate public endpoint requested.")
    if not payload.public_base_url:
        return JSONResponse({"success": False, "message": "URL is required."})
        
    res = await check_public_url(payload.public_base_url)
    success = res["status"] in ("ok", "warn") # Warn might just be 404, but it's reachable. Actually we check /health to return 200.
    
    if res["status"] == "ok":
        msg = "Public endpoint responds correctly."
    else:
        msg = f"Reachable but warning: {res.get('message', '')}"
        
    if res["status"] == "fail":
        success = False
        msg = f"Failed to reach endpoint: {res.get('message', '')}"
    
    return JSONResponse(content={
        "success": success,
        "message": msg,
    })


@router.post("/save")
async def save_config(config: PersistedConfig, persistence=Depends(get_persistence)) -> JSONResponse:
    """Save configuration values from the setup form."""
    try:
        if persistence:
            persistence.save_config(config)
            
            # Apply to current settings instance immediately
            config_svc = registry.get("config_service")
            if config_svc:
                config_svc.settings.apply_persisted(config)
                
            # Recreate MA Client with new settings
            new_client = MusicAssistantClient(
                base_url=config.ma_base_url,
                token=config.ma_token
            )
            registry.register("ma_client", new_client)
            
        return JSONResponse(content={
            "success": True,
            "message": "Configuration saved! Some changes may require full add-on restart.",
        })
    except Exception as exc:
        logger.exception("Error saving setup config.")
        return JSONResponse(
            content={"success": False, "message": str(exc)},
            status_code=400,
        )
