"""Validate that configured public endpoints meet Alexa requirements."""

from __future__ import annotations

import logging
from urllib.parse import urlparse

from app.core.exceptions import EndpointValidationError

logger = logging.getLogger(__name__)


def validate_public_endpoint(url: str, *, allow_insecure: bool = False) -> None:
    """Raise ``EndpointValidationError`` if *url* is not suitable for Alexa.

    Alexa requires HTTPS endpoints that are publicly reachable.
    """
    if not url:
        raise EndpointValidationError("Public endpoint URL is empty.")

    parsed = urlparse(url)

    if not allow_insecure and parsed.scheme != "https":
        raise EndpointValidationError(
            f"Public endpoint must use HTTPS, got '{parsed.scheme}'."
        )

    if parsed.hostname in ("localhost", "127.0.0.1", "::1"):
        raise EndpointValidationError(
            "Public endpoint must not be localhost."
        )

    # Check for private IP ranges (basic heuristic)
    host = parsed.hostname or ""
    if host.startswith("192.168.") or host.startswith("10.") or host.startswith("172."):
        logger.warning(
            "Public endpoint appears to use a private IP: %s. "
            "Alexa probably cannot reach it.",
            host,
        )

    logger.debug("Endpoint validation passed: %s", url)
