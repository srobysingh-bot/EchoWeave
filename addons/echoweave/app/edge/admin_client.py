from __future__ import annotations

import logging
import os
from typing import Any

import httpx

logger = logging.getLogger(__name__)


async def fetch_worker_home_status(*, worker_base_url: str, tenant_id: str, home_id: str) -> dict[str, Any]:
    """Fetch edge provisioning status from Worker admin API.

    Returns a normalized dictionary safe for UI diagnostics.
    """
    if not worker_base_url or not tenant_id or not home_id:
        return {
            "reachable": False,
            "provisioned": False,
            "alexa_account_linked": False,
            "connector_online": False,
            "message": "missing worker_base_url or tenant/home identifiers",
        }

    endpoint = f"{worker_base_url.rstrip('/')}/v1/admin/homes/{tenant_id}/{home_id}/status"
    headers: dict[str, str] = {"accept": "application/json"}
    admin_key = os.getenv("ECHOWEAVE_WORKER_ADMIN_API_KEY", "").strip()
    if admin_key:
        headers["authorization"] = f"Bearer {admin_key}"

    try:
        timeout = httpx.Timeout(8.0, connect=4.0)
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.get(endpoint, headers=headers)

        if resp.status_code == 404:
            return {
                "reachable": True,
                "provisioned": False,
                "alexa_account_linked": False,
                "connector_online": False,
                "message": "home not provisioned in worker",
            }

        if resp.status_code == 401:
            return {
                "reachable": True,
                "provisioned": False,
                "alexa_account_linked": False,
                "connector_online": False,
                "message": "worker admin endpoint unauthorized",
            }

        if resp.status_code != 200:
            return {
                "reachable": True,
                "provisioned": False,
                "alexa_account_linked": False,
                "connector_online": False,
                "message": f"worker status request failed ({resp.status_code})",
            }

        data = resp.json()
        result = data.get("result", {}) if isinstance(data, dict) else {}
        connector = result.get("connector", {}) if isinstance(result, dict) else {}

        return {
            "reachable": True,
            "provisioned": True,
            "alexa_account_linked": bool(result.get("alexa_account_linked", False)),
            "connector_online": bool(connector.get("online", False)),
            "connector_registration_status": str(connector.get("registration_status", "unknown")),
            "origin_base_url": str(result.get("origin_base_url", "")),
            "queue_binding": str(result.get("queue_binding", "")),
            "message": "ok",
        }
    except Exception as exc:
        logger.warning("Worker provisioning status fetch failed: %s", exc)
        return {
            "reachable": False,
            "provisioned": False,
            "alexa_account_linked": False,
            "connector_online": False,
            "message": "worker status unreachable",
        }
