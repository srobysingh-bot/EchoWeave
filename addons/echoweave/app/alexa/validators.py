"""Validate incoming Alexa request payloads."""

from __future__ import annotations

from typing import Any, Optional


def validate_alexa_request(body: dict[str, Any]) -> Optional[str]:
    """Return an error message if *body* is not a valid Alexa request envelope.

    Returns ``None`` if the request looks valid.
    """
    if not isinstance(body, dict):
        return "Request body is not a JSON object."

    if "version" not in body:
        return "Missing 'version' field in Alexa request."

    request = body.get("request")
    if not isinstance(request, dict):
        return "Missing or invalid 'request' object."

    if "type" not in request:
        return "Missing 'type' field in request."

    # Validate session (present for most request types, but not AudioPlayer events)
    request_type = request.get("type", "")
    if not request_type.startswith("AudioPlayer.") and not request_type.startswith("PlaybackController."):
        session = body.get("session")
        if not isinstance(session, dict):
            return "Missing 'session' object for non-AudioPlayer request."

    return None


def extract_device_id(body: dict[str, Any]) -> str:
    """Extract the Alexa device ID from the request context.

    Returns ``"unknown"`` if the device ID cannot be found.
    """
    return (
        body.get("context", {})
        .get("System", {})
        .get("device", {})
        .get("deviceId", "unknown")
    )


def extract_user_id(body: dict[str, Any]) -> str:
    """Extract the Alexa user ID from the session or context."""
    # Try session first
    user_id = body.get("session", {}).get("user", {}).get("userId", "")
    if user_id:
        return user_id
    # Fall back to context
    return (
        body.get("context", {})
        .get("System", {})
        .get("user", {})
        .get("userId", "unknown")
    )
