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
        
        # Diagnostic: Try to extract player and item info for "UI Interception" research
        stream_url = body.get("streamUrl", "")
        if "/flow/" in stream_url:
            parts = stream_url.split("/")
            # Standard MA flow URL: .../flow/session_id/player_id/item_id/...
            try:
                # Based on user logs: http://[local_ip]:8097/flow/rMNLf4yz/Amit's Echo Spot/e0efa3a074dc44428a9a10dceb8acf77/Amit's Echo Spot.flac
                if len(parts) >= 8:
                    player_id = parts[5]
                    item_id = parts[6]
                    import json as _json
                    logger.info(_json.dumps({
                        "event": "ma_push_url_parsed",
                        "player_id": player_id,
                        "item_id": item_id,
                        "intercept_possible": True
                    }))
            except Exception:
                pass
    except Exception:
        logger.warning("Received Music Assistant push-url with invalid JSON body.")
    
    return JSONResponse(content={"status": "ok"}, status_code=200)
