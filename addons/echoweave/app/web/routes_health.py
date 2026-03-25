"""Machine-readable health endpoint."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse

from app.core.constants import APP_NAME, APP_VERSION, HEALTH_KEY_SERVICE

router = APIRouter(tags=["health"])


@router.get("/healthz")
async def healthz() -> JSONResponse:
    """Return lightweight liveness status without running nested checks."""
    return JSONResponse(
        content={
            "status": "ok",
            "version": APP_VERSION,
            "checks": [
                {
                    "key": HEALTH_KEY_SERVICE,
                    "status": "ok",
                    "message": f"{APP_NAME} v{APP_VERSION} is running.",
                }
            ],
        },
        status_code=200,
    )


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

    from app.dependencies import get_health_service
    health_svc = get_health_service()
    
    if health_svc:
        result = await health_svc.run_all()
        checks.extend([c.model_dump(mode="json") for c in result.checks])

    overall = "ok"
    if any(c["status"] == "warn" for c in checks):
        overall = "degraded"
    if any(c["status"] == "fail" for c in checks):
        overall = "fail"

    return JSONResponse(
        content={
            "status": overall,
            "version": APP_VERSION,
            "checks": checks,
        },
        status_code=200 if overall in ("ok", "degraded") else 503,
    )
