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


def verify_alexa_timestamp(body: dict[str, Any]) -> bool:
    """Ensure the request timestamp is within 150 seconds of current time."""
    from datetime import datetime, timezone
    timestamp_str = body.get("request", {}).get("timestamp")
    if not timestamp_str:
        return False
    try:
        clean_ts = timestamp_str.replace("Z", "+00:00")
        ts = datetime.fromisoformat(clean_ts)
        # If naive (which it shouldn't be with +00:00), force it to UTC for comparison
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        now = datetime.now(timezone.utc)
        delta = abs((now - ts).total_seconds())
        return delta <= 150
    except Exception:
        return False


async def verify_alexa_signature(request: Any, raw_body: bytes, enforce: bool = False) -> bool:
    """Base framework for verifying the SignatureCertChainUrl and Signature.
    
    TODO: Implement full RSA validation via the specified public certificate.
    """
    cert_url = request.headers.get("SignatureCertChainUrl")
    signature = request.headers.get("Signature")
    
    if not cert_url or not signature:
        return not enforce

    # Full cert validation goes here in Phase 2
    return True
