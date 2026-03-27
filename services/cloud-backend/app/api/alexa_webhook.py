from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from app.core.connector_registry import registry
from app.core.session_registry import session_registry

router = APIRouter(prefix="/v1/alexa", tags=["alexa"])
logger = logging.getLogger(__name__)

_LAUNCH_RESPONSE = {
    "version": "1.0",
    "sessionAttributes": {},
    "response": {
        "outputSpeech": {
            "type": "PlainText",
            "text": "Welcome to EchoWeave.",
        },
        "reprompt": {
            "outputSpeech": {
                "type": "PlainText",
                "text": "EchoWeave is ready.",
            }
        },
        "shouldEndSession": False,
    },
}


def _speech_response(text: str, should_end_session: bool = False) -> dict[str, Any]:
    return {
        "version": "1.0",
        "sessionAttributes": {},
        "response": {
            "outputSpeech": {
                "type": "PlainText",
                "text": text,
            },
            "shouldEndSession": should_end_session,
        },
    }


def _extract_request_info(body: dict[str, Any]) -> dict[str, str]:
    request = body.get("request", {})
    session = body.get("session", {})
    context = body.get("context", {})
    system = context.get("System", {})
    intent = request.get("intent", {})

    return {
        "request_type": str(request.get("type", "")),
        "intent_name": str(intent.get("name", "")),
        "request_id": str(request.get("requestId", "")),
        "session_id": str(session.get("sessionId", "")),
        "user_id": str(system.get("user", {}).get("userId", "")),
    }


def _resolve_tenant_home(body: dict[str, Any]) -> tuple[str, str, str]:
    session = body.get("session", {})
    attrs = session.get("attributes", {}) or {}
    session_id = str(session.get("sessionId", ""))

    tenant_id = str(attrs.get("tenant_id", "")).strip()
    home_id = str(attrs.get("home_id", "")).strip()
    if tenant_id and home_id:
        if session_id:
            session_registry.put(session_id, {"tenant_id": tenant_id, "home_id": home_id})
        return tenant_id, home_id, "session_attributes"

    if session_id:
        prior = session_registry.get(session_id) or {}
        prev_tenant = str(prior.get("tenant_id", "")).strip()
        prev_home = str(prior.get("home_id", "")).strip()
        if prev_tenant and prev_home:
            return prev_tenant, prev_home, "session_registry"

    default_connector = registry.find_default()
    if default_connector:
        return default_connector.tenant_id, default_connector.home_id, "default_connector"

    return "", "", "unresolved"


def _dispatch_to_connector(*, request_type: str, intent_name: str, connector_id: str) -> dict[str, Any]:
    if request_type == "LaunchRequest":
        return {
            "success": True,
            "connector_id": connector_id,
            "alexa_response": _LAUNCH_RESPONSE,
            "dispatch_note": "launch-routed",
        }

    if request_type == "IntentRequest" and (intent_name == "PlayIntent" or "Play" in intent_name):
        return {
            "success": True,
            "connector_id": connector_id,
            "alexa_response": _speech_response("Playing now from Music Assistant."),
            "dispatch_note": "play-routed",
        }

    return {
        "success": False,
        "connector_id": connector_id,
        "alexa_response": _speech_response("Sorry, that request is not supported yet.", should_end_session=True),
        "dispatch_note": "unsupported-request",
    }


@router.post("")
@router.post("/")
async def alexa_webhook(body: dict) -> JSONResponse:
    info = _extract_request_info(body)
    logger.info("alexa_request type=%s intent=%s request_id=%s", info["request_type"], info["intent_name"], info["request_id"])
    logger.info(
        "alexa_request_summary session_id=%s user_id=%s has_session_attributes=%s",
        info["session_id"],
        info["user_id"],
        bool((body.get("session", {}).get("attributes", {}) or {})),
    )

    try:
        tenant_id, home_id, source = _resolve_tenant_home(body)
        logger.info("tenant_home_resolve tenant_id=%s home_id=%s source=%s", tenant_id, home_id, source)

        connector = None
        if tenant_id and home_id:
            connector = registry.find_by_tenant_home(tenant_id=tenant_id, home_id=home_id)
        if connector is None:
            connector = registry.find_default()

        if connector is None:
            logger.warning("connector_lookup result=not-found tenant_id=%s home_id=%s", tenant_id, home_id)
            if info["request_type"] == "LaunchRequest":
                logger.info("connector_dispatch_result connector_id=none success=True note=launch-no-connector")
                logger.info("alexa_response payload=%s", _LAUNCH_RESPONSE)
                return JSONResponse(content=_LAUNCH_RESPONSE)
            final_payload = _speech_response(
                "No connector is available yet. Please try again in a moment.",
                should_end_session=True,
            )
            logger.info("alexa_response payload=%s", final_payload)
            return JSONResponse(content=final_payload)

        logger.info(
            "connector_lookup result=found connector_id=%s status=%s heartbeat=%s",
            connector.connector_id,
            connector.status,
            connector.last_heartbeat_status,
        )

        logger.info(
            "connector_dispatch_attempt connector_id=%s request_type=%s intent=%s",
            connector.connector_id,
            info["request_type"],
            info["intent_name"],
        )

        dispatch = _dispatch_to_connector(
            request_type=info["request_type"],
            intent_name=info["intent_name"],
            connector_id=connector.connector_id,
        )
        logger.info(
            "connector_dispatch_result connector_id=%s success=%s note=%s",
            dispatch["connector_id"],
            dispatch["success"],
            dispatch["dispatch_note"],
        )
        logger.info("alexa_response payload=%s", dispatch["alexa_response"])
        return JSONResponse(content=dispatch["alexa_response"])
    except Exception:
        logger.exception("alexa_webhook_exception")
        final_payload = _speech_response(
            "Sorry, something went wrong while processing your request.",
            should_end_session=True,
        )
        logger.info("alexa_response payload=%s", final_payload)
        return JSONResponse(content=final_payload)
