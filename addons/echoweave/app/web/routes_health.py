"""Machine-readable health endpoint."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse

from app.core.constants import APP_NAME, APP_VERSION, HEALTH_KEY_SERVICE

router = APIRouter(tags=["health"])


@router.get("/health")
async def health_check() -> JSONResponse:
    """Return JSON health status for monitoring and load-balancer probes.

    The response always includes the service's own status.  Subsystem
    checks (MA connectivity, stream URL, etc.) are added when the
    diagnostics layer is wired up.
    """
    checks: list[dict[str, Any]] = [
        {
            "key": HEALTH_KEY_SERVICE,
            "status": "ok",
            "message": f"{APP_NAME} v{APP_VERSION} is running.",
        }
    ]

    # TODO: Pull additional checks from DiagnosticsHealthService once
    # the service registry is wired into this route.

    overall = "ok" if all(c["status"] == "ok" for c in checks) else "degraded"

    return JSONResponse(
        content={
            "status": overall,
            "version": APP_VERSION,
            "checks": checks,
        },
        status_code=200 if overall == "ok" else 503,
    )
