"""Bearer token management for Music Assistant API."""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


def build_auth_headers(token: str) -> dict[str, str]:
    """Return HTTP headers for MA API authentication.

    Uses ``Authorization: Bearer <token>`` as required by the Music Assistant
    long-lived token model.
    """
    if not token:
        logger.warning("MA token is empty — requests will be unauthenticated.")
        return {}
    return {"Authorization": f"Bearer {token}"}
