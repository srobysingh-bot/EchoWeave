"""Setup wizard page — guides users through initial configuration."""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Request, Depends
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel

from app.core.constants import APP_VERSION
from app.dependencies import get_persistence
from app.storage.models import PersistedConfig, SkillMetadata
from app.ma.client import MusicAssistantClient
from app.diagnostics.checks import check_public_url
from app.core.service_registry import registry
from app.settings import Settings
from app.web.ingress import get_ingress_base_path

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/setup", tags=["setup"])
templates = Jinja2Templates(directory="app/web/templates")


def _build_checklist(settings: Any, persistence: Any) -> list[dict[str, Any]]:
    """Build the setup checklist with mode-aware completion status."""
    has_ma = settings.ma_configured

    if getattr(settings, "is_connector_mode", False):
        return [
            {"step": 1, "label": "Connector Backend URL", "done": bool(settings.backend_url), "detail": "Set cloud backend URL"},
            {"step": 2, "label": "Connector Identity", "done": bool(settings.connector_id and settings.connector_secret), "detail": "Set connector ID and secret"},
            {"step": 3, "label": "Tenant/Home Mapping", "done": bool(settings.tenant_id and settings.home_id), "detail": "Set tenant_id and home_id"},
            {"step": 4, "label": "Music Assistant Reachable", "done": has_ma, "detail": "Configure MA URL and token"},
        ]

    # Legacy mode checklist
    has_public = settings.public_configured
    meta = persistence.load_skill_metadata() if persistence else None
    has_skill = bool(meta and meta.skill_id)
    manual_ask_setup = bool(meta and meta.manual_ask_setup)

    return [
        {"step": 1, "label": "Music Assistant Reachable", "done": has_ma, "detail": "Configure MA URL"},
        {"step": 2, "label": "Music Assistant Token", "done": bool(settings.ma_token), "detail": "Provide long-lived token"},
        {"step": 3, "label": "Public URL Configured", "done": has_public, "detail": "Set public_base_url"},
        {"step": 4, "label": "Stream Endpoint Configured", "done": settings.stream_configured, "detail": "HTTPS stream endpoint"},
        {"step": 5, "label": "ASK Setup (Optional in Phase 1)", "done": manual_ask_setup, "detail": "Manual ASK credential import"},
        {"step": 6, "label": "Alexa Skill Created", "done": has_skill, "detail": "Create or link skill"},
    ]


@router.get("", response_class=HTMLResponse)
@router.get("/", response_class=HTMLResponse)
async def setup_page(request: Request, persistence=Depends(get_persistence)) -> HTMLResponse:
    """Render the setup wizard."""
    config_svc = registry.get_optional("config_service")
    if config_svc:
        settings = config_svc.settings
    else:
        settings = Settings()

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
            "version": APP_VERSION,
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
            await client.close()
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
    success = res["status"] == "ok"
    msg = res.get("message", "Validation completed.")
    
    return JSONResponse(content={
        "success": success,
        "message": msg,
    })


class SaveSkillRequest(BaseModel):
    """Request to manually link an Alexa skill."""
    skill_id: str
    endpoint_url: str = ""
    manual_ask_setup: bool = False

@router.post("/save-skill")
async def save_skill(payload: SaveSkillRequest, persistence=Depends(get_persistence)) -> JSONResponse:
    """Save manually configured Alexa skill metadata (Phase 1 manual setup mode)."""
    logger.info("Manual skill setup requested for skill_id: %s", payload.skill_id)
    
    if not payload.skill_id or not payload.skill_id.strip():
        return JSONResponse(
            {"success": False, "message": "Skill ID is required."},
            status_code=400,
        )
    
    if not persistence:
        return JSONResponse(
            {"success": False, "message": "Persistence service not available."},
            status_code=500,
        )
    
    try:
        # Load existing metadata or create new one
        meta = persistence.load_skill_metadata() or SkillMetadata()
        
        # Update with manual values
        meta.skill_id = payload.skill_id.strip()
        meta.endpoint_url = payload.endpoint_url.strip() if payload.endpoint_url else meta.endpoint_url
        meta.manual_skill_configured = True
        meta.manual_ask_setup = payload.manual_ask_setup
        
        # Save to persistence
        persistence.save_skill_metadata(meta)
        
        return JSONResponse({
            "success": True,
            "message": f"Skill {payload.skill_id} linked successfully. Setup checklist will update on reload.",
        })
    except Exception as exc:
        logger.exception("Error saving manual skill configuration.")
        return JSONResponse(
            {"success": False, "message": f"Error: {exc}"},
            status_code=500,
        )


@router.post("/save")
async def save_config(config: PersistedConfig, persistence=Depends(get_persistence)) -> JSONResponse:
    """Save configuration values from the setup form."""
    try:
        config_svc = registry.get_optional("config_service")
        if config_svc:
            config_svc.save_persisted(config)
            settings = config_svc.settings
        elif persistence:
            persistence.save_config(config)
            settings = config
        else:
            settings = config

        # Recreate MA Client with new settings
        existing_client = registry.get_optional("ma_client")
        if existing_client:
            try:
                await existing_client.close()
            except Exception:
                logger.debug("Existing MA client close failed during config save.", exc_info=True)

        new_client = MusicAssistantClient(
            base_url=settings.ma_base_url,
            token=settings.ma_token
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
