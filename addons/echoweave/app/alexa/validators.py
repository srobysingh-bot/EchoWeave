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


async def verify_alexa_signature(request: Any, raw_body: bytes, enforce: bool = True) -> bool:
    """Fully verify the Alexa SignatureCertChainUrl and Signature header.
    
    1. Validate the S3 URL structure.
    2. Download the certificate.
    3. Ensure SAN contains 'echo-api.amazon.com' and the cert is valid.
    4. Base64 decode the signature and verify the raw body via RSA-SHA1.
    """
    import base64
    import logging
    from urllib.parse import urlparse
    import httpx
    
    logger = logging.getLogger(__name__)

    cert_url = request.headers.get("SignatureCertChainUrl")
    signature_b64 = request.headers.get("Signature")
    
    if not cert_url or not signature_b64:
        if enforce:
            logger.warning("Missing Alexa signature headers.")
        return not enforce

    if not enforce:
        return True

    # 1. URL checks
    try:
        parsed_url = urlparse(cert_url)
        if parsed_url.scheme.lower() != "https" or parsed_url.hostname.lower() != "s3.amazonaws.com":
            return False
        if not parsed_url.path.startswith("/echo.api/"):
            return False
        if parsed_url.port and parsed_url.port != 443:
            return False
    except Exception:
        return False

    # 2. Fetch cert
    try:
        async with httpx.AsyncClient(timeout=5) as client:
            resp = await client.get(cert_url)
            resp.raise_for_status()
            cert_pem = resp.content
    except Exception as e:
        logger.warning("Failed to download Alexa certificate: %s", e)
        return False

    # 3. Validate Subject Alternative Name & Time
    try:
        from cryptography import x509
        from cryptography.hazmat.primitives.asymmetric import padding
        from cryptography.hazmat.primitives import hashes
        
        cert = x509.load_pem_x509_certificate(cert_pem)
        
        ext = cert.extensions.get_extension_for_class(x509.SubjectAlternativeName)
        names = ext.value.get_values_for_type(x509.DNSName)
        if "echo-api.amazon.com" not in names:
            logger.warning("Cert does not contain echo-api.amazon.com SAN.")
            return False

        from datetime import datetime, timezone
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        if now < cert.not_valid_before or now > cert.not_valid_after:
            logger.warning("Alexa certificate is expired or not valid yet.")
            return False

        target_pub_key = cert.public_key()
        signature_bytes = base64.b64decode(signature_b64)
        
        target_pub_key.verify(
            signature_bytes,
            raw_body,
            padding.PKCS1v15(),
            hashes.SHA1()
        )
        return True
    except Exception as e:
        logger.warning("Alexa signature cryptographic verification failed: %s", e)
        return False
