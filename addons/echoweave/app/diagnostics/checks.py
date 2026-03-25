"""Individual diagnostic checks for each subsystem."""

from __future__ import annotations

import logging
from typing import Any
from urllib.parse import urlparse, urljoin

import httpx

logger = logging.getLogger(__name__)


async def check_public_url(public_base_url: str) -> dict[str, Any]:
    """Verify that the configured public URL is reachable from the internet."""
    if not public_base_url:
        return {"key": "public_url_reachable", "status": "warn", "message": "Public URL not configured."}

    parsed = urlparse(public_base_url)
    host = (parsed.hostname or "").lower()
    is_localish = host in {"localhost", "127.0.0.1", "0.0.0.0", "homeassistant", "supervisor"} or host.endswith((".local", ".lan", ".internal", ".home"))

    try:
        probe_url = urljoin(public_base_url.rstrip("/") + "/", "healthz")
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(probe_url)

        if resp.status_code == 200 and parsed.scheme == "https" and not is_localish:
            return {
                "key": "public_url_reachable",
                "status": "ok",
                "message": "Public HTTPS endpoint is reachable and Alexa-ready.",
            }

        if resp.status_code == 200:
            return {
                "key": "public_url_reachable",
                "status": "warn",
                "message": "Endpoint is reachable for local testing but not Alexa-ready; use public HTTPS.",
            }

        if 400 <= resp.status_code < 500:
            return {
                "key": "public_url_reachable",
                "status": "warn",
                "message": f"Public endpoint is reachable but invalid (HTTP {resp.status_code}).",
            }

        if resp.status_code >= 500:
            return {
                "key": "public_url_reachable",
                "status": "fail",
                "message": f"Public endpoint returned server error (HTTP {resp.status_code}).",
            }

        return {
            "key": "public_url_reachable",
            "status": "warn",
            "message": f"Public endpoint returned unexpected HTTP {resp.status_code}.",
        }
    except Exception as exc:
        return {
            "key": "public_url_reachable",
            "status": "fail",
            "message": f"Unreachable: {type(exc).__name__}: {exc!r}",
        }


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
