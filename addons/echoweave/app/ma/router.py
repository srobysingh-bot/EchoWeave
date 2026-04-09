"""Music Assistant callback router.

Handles inbound requests from Music Assistant, such as push-url notifications.
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/ma", tags=["ma"])


@router.post("/push-url")
async def ma_push_url(request: Request) -> JSONResponse:
    """Handle Music Assistant push-url registration/notification.
    
    This endpoint is often called by Music Assistant to register its callback URL.
    We acknowledge the request to prevent 404 errors in the MA UI.
    """
    try:
        body = await request.json()
        logger.info("Received Music Assistant push-url: %s", body)
    except Exception:
        logger.warning("Received Music Assistant push-url with invalid JSON body.")
    
    return JSONResponse(content={"status": "ok"}, status_code=200)
