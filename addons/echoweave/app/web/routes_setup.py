"""Setup wizard page — guides users through initial configuration."""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/setup", tags=["setup"])
templates = Jinja2Templates(directory="app/web/templates")


def _build_checklist() -> list[dict[str, Any]]:
    """Build the setup checklist with current completion status.

    TODO: Wire up to actual service checks via the diagnostics layer.
    """
    return [
        {"step": 1, "label": "Music Assistant Reachable", "done": False, "detail": "Configure MA URL"},
        {"step": 2, "label": "Music Assistant Token Valid", "done": False, "detail": "Provide long-lived token"},
        {"step": 3, "label": "Public URL Configured", "done": False, "detail": "Set public_base_url"},
        {"step": 4, "label": "Reverse Proxy Reachable", "done": False, "detail": "Verify HTTPS endpoint"},
        {"step": 5, "label": "ASK Credentials Present", "done": False, "detail": "Configure AWS credentials"},
        {"step": 6, "label": "Alexa Skill Created", "done": False, "detail": "Create or link skill"},
    ]


@router.get("", response_class=HTMLResponse)
@router.get("/", response_class=HTMLResponse)
async def setup_page(request: Request) -> HTMLResponse:
    """Render the setup wizard."""
    checklist = _build_checklist()
    complete = sum(1 for item in checklist if item["done"])
    total = len(checklist)

    return templates.TemplateResponse(
        request,
        "setup.html",
        {
            "checklist": checklist,
            "complete": complete,
            "total": total,
            "progress_pct": int(complete / total * 100) if total else 0,
        },
    )


@router.post("/validate-ma")
async def validate_ma(request: Request) -> JSONResponse:
    """Validate Music Assistant connectivity.

    TODO: Use the MA client to ping the server and validate the token.
    """
    logger.info("Validate MA requested.")
    return JSONResponse(content={
        "success": False,
        "message": "MA validation not yet wired up — configure MA URL and token first.",
    })


@router.post("/validate-public")
async def validate_public(request: Request) -> JSONResponse:
    """Validate public endpoint reachability.

    TODO: Make an outbound request to the configured public_base_url.
    """
    logger.info("Validate public endpoint requested.")
    return JSONResponse(content={
        "success": False,
        "message": "Public endpoint validation not yet wired up.",
    })


@router.post("/save")
async def save_config(request: Request) -> JSONResponse:
    """Save configuration values from the setup form.

    TODO: Persist values via the ConfigService / PersistenceService.
    """
    try:
        body = await request.json()
        logger.info("Setup save requested with keys: %s", list(body.keys()))
        return JSONResponse(content={
            "success": True,
            "message": "Configuration save is not yet implemented.",
        })
    except Exception as exc:
        logger.exception("Error saving setup config.")
        return JSONResponse(
            content={"success": False, "message": str(exc)},
            status_code=400,
        )
