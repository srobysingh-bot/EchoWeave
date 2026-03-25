"""Main Alexa webhook endpoint.

Receives POST requests from the Alexa service, classifies the request type,
and dispatches to the appropriate handler.
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from app.alexa.intents import handle_intent
from app.alexa.playback_events import handle_playback_event
from app.alexa.response_builder import build_response, build_error_response
from app.alexa.validators import validate_alexa_request

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/alexa", tags=["alexa"])


@router.post("")
@router.post("/")
async def alexa_webhook(request: Request) -> JSONResponse:
    """Alexa skill endpoint — receives all Alexa requests.

    Request types handled:
      - LaunchRequest
      - IntentRequest
      - AudioPlayer.* events
      - SessionEndedRequest
      - PlaybackController.* commands
    """
    try:
        body: dict[str, Any] = await request.json()
    except Exception:
        logger.warning("Failed to parse Alexa request body.")
        return JSONResponse(
            content=build_error_response("Invalid request body."),
            status_code=400,
        )

    from app.alexa.validators import validate_alexa_request, verify_alexa_timestamp, verify_alexa_signature
    
    # 1. Base JSON structure validation
    validation_error = validate_alexa_request(body)
    if validation_error:
        logger.warning("Alexa request validation failed: %s", validation_error)
        return JSONResponse(
            content=build_error_response(validation_error),
            status_code=400,
        )

    # 2. Timestamp freshness
    if not verify_alexa_timestamp(body):
        logger.warning("Alexa request timestamp is missing or too old.")
        return JSONResponse(
            content=build_error_response("Request timestamp is too old."),
            status_code=400,
        )

    # 3. Request Signature Verification
    from app.core.service_registry import registry
    config_svc = registry.get("config_service")
    enforce = True
    if config_svc and getattr(config_svc.settings, "alexa_validation_mode", "enforce") != "enforce":
        enforce = False
        
    raw_body = await request.body()
    if not await verify_alexa_signature(request, raw_body, enforce=enforce):
        logger.warning("Alexa request signature verification failed.")
        return JSONResponse(
            content=build_error_response("Invalid request signature."),
            status_code=400,
        )

    request_type = body.get("request", {}).get("type", "")
    intent_name = body.get("request", {}).get("intent", {}).get("name", "")
    logger.info("Alexa request received: type=%s intent=%s", request_type, intent_name or "<none>")

    try:
        if request_type == "LaunchRequest":
            try:
                response = _handle_launch()
                logger.info("LaunchRequest handled successfully.")
                return JSONResponse(content=response)
            except Exception:
                logger.exception("LaunchRequest handling failed.")
                raise

        elif request_type == "IntentRequest":
            result = await handle_intent(body)
            return JSONResponse(content=result)

        elif request_type.startswith("AudioPlayer."):
            result = await handle_playback_event(body)
            return JSONResponse(content=result)

        elif request_type.startswith("PlaybackController."):
            # TODO: Implement PlaybackController commands.
            logger.info("PlaybackController request received: %s", request_type)
            return JSONResponse(content=build_response())

        elif request_type == "SessionEndedRequest":
            reason = body.get("request", {}).get("reason", "unknown")
            logger.info("Session ended: %s", reason)
            return JSONResponse(content=build_response())

        else:
            logger.warning("Unhandled Alexa request type: %s", request_type)
            return JSONResponse(content=build_response())

    except Exception:
        logger.exception("Unhandled error processing Alexa request.")
        return JSONResponse(
            content=build_error_response("Internal error processing your request."),
            status_code=500,
        )


def _handle_launch() -> dict[str, Any]:
    """Respond to LaunchRequest with a welcome message."""
    return build_response(
        speech="Welcome to EchoWeave. You can say play audio to begin.",
        reprompt="Say play audio to start playback, or say help for more options.",
        should_end_session=False,
    )
