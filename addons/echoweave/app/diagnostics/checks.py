"""Individual diagnostic checks for each subsystem."""

from __future__ import annotations

import logging
from typing import Any

import httpx

logger = logging.getLogger(__name__)


async def check_public_url(public_base_url: str) -> dict[str, Any]:
    """Verify that the configured public URL is reachable from the internet."""
    if not public_base_url:
        return {"key": "public_url_reachable", "status": "warn", "message": "Public URL not configured."}
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(f"{public_base_url}/health")
        return {
            "key": "public_url_reachable",
            "status": "ok" if resp.status_code == 200 else "warn",
            "message": f"Public endpoint responded with {resp.status_code}.",
        }
    except Exception as exc:
        return {"key": "public_url_reachable", "status": "fail", "message": f"Unreachable: {exc}"}


async def check_ask_configured(data_dir: str) -> dict[str, Any]:
    """Check whether ASK credentials are present in the data directory."""
    from pathlib import Path
    ask_dir = Path(data_dir) / "ask"
    has_creds = ask_dir.is_dir() and any(ask_dir.iterdir()) if ask_dir.is_dir() else False
    return {
        "key": "ask_configured",
        "status": "ok" if has_creds else "warn",
        "message": "ASK credentials found." if has_creds else "No ASK credentials configured.",
    }


async def check_skill_exists(persistence) -> dict[str, Any]:
    """Check whether a skill ID has been stored."""
    meta = persistence.load_skill_metadata() if persistence else None
    if meta and meta.skill_id:
        return {"key": "skill_exists", "status": "ok", "message": f"Skill ID: {meta.skill_id}"}
    return {"key": "skill_exists", "status": "warn", "message": "No Alexa skill configured."}
