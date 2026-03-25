"""Derive externally-reachable stream URLs for Alexa playback.

Alexa devices fetch audio streams directly, so the URL *must* be:
  - Public HTTPS (not localhost, not internal ingress).
  - Reachable from the internet.
  - Returning a supported audio content-type.

This module builds such URLs from the configured ``stream_base_url``.
"""

from __future__ import annotations

import logging
from urllib.parse import quote, urlparse, urljoin
import ipaddress

from app.ma.models import MAQueueItem
from app.core.exceptions import StreamResolutionError

logger = logging.getLogger(__name__)

STREAM_PATH_HINT = "/stream/<queue_id>/<queue_item_id>"

def is_valid_alexa_stream_url(url: str, allow_insecure: bool) -> bool:
    """Return True if the URL is public HTTPS, or if insecure overrides are allowed."""
    try:
        parsed = urlparse(url)
        if not allow_insecure and parsed.scheme != "https":
            return False
            
        hostname = parsed.hostname or ""
        
        # Obvious internal short names
        if hostname.lower() in ("localhost", "homeassistant", "supervisor", "host.docker.internal"):
            return allow_insecure
            
        # Obvious internal suffixes
        if hostname.lower().endswith((".local", ".internal", ".test", ".lan", ".home")):
            return allow_insecure
            
        try:
            ip = ipaddress.ip_address(hostname)
            if ip.is_private or ip.is_loopback:
                return allow_insecure
        except ValueError:
            pass
        return True
    except Exception:
        return False

class StreamResolver:
    """Build externally reachable stream URLs from ``stream_base_url``."""

    def __init__(self, stream_base_url: str, allow_insecure: bool = False) -> None:
        self._base = stream_base_url.rstrip("/") if stream_base_url else ""
        self._allow_insecure = allow_insecure

    def resolve(self, item: MAQueueItem) -> str:
        """Return a public HTTPS URL that Alexa can use to stream this item.

        If the item already has a globally-reachable URL in its stream details,
        that URL is returned directly.  Otherwise, the URL is constructed from
        ``stream_base_url`` plus the item's queue/item identifiers.
        """
        if item.streamdetails and item.streamdetails.url:
            url = item.streamdetails.url
            if is_valid_alexa_stream_url(url, self._allow_insecure):
                logger.debug("Using MA-provided stream URL for item %s", item.queue_item_id)
                return url

        if not self._base:
            logger.error(
                "stream_base_url is not configured — cannot build a public stream URL."
            )
            # Cannot fall back, Alexa requires a valid URL.
            raise StreamResolutionError("stream_base_url is missing.")

        path = f"/stream/{quote(item.queue_id, safe='')}/{quote(item.queue_item_id, safe='')}"
        public_url = urljoin(self._base + "/", path.lstrip("/"))
        
        if not is_valid_alexa_stream_url(public_url, self._allow_insecure):
            raise StreamResolutionError(f"Resolved URL '{public_url}' fails Alexa public HTTPS policy.")

        logger.debug("Resolved stream URL: %s", public_url)
        return public_url
