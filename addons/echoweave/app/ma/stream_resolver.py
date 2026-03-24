"""Derive externally-reachable stream URLs for Alexa playback.

Alexa devices fetch audio streams directly, so the URL *must* be:
  - Public HTTPS (not localhost, not internal ingress).
  - Reachable from the internet.
  - Returning a supported audio content-type.

This module builds such URLs from the configured ``stream_base_url``.
"""

from __future__ import annotations

import logging
from urllib.parse import quote, urljoin

from app.ma.models import MAQueueItem

logger = logging.getLogger(__name__)


class StreamResolver:
    """Build externally reachable stream URLs from ``stream_base_url``."""

    def __init__(self, stream_base_url: str) -> None:
        self._base = stream_base_url.rstrip("/") if stream_base_url else ""

    def resolve(self, item: MAQueueItem) -> str:
        """Return a public HTTPS URL that Alexa can use to stream this item.

        If the item already has a globally-reachable URL in its stream details,
        that URL is returned directly.  Otherwise, the URL is constructed from
        ``stream_base_url`` plus the item's queue/item identifiers.
        """
        # If MA already provides an externally-reachable URL, prefer it.
        if item.streamdetails and item.streamdetails.url:
            url = item.streamdetails.url
            if url.startswith("https://"):
                logger.debug("Using MA-provided stream URL for item %s", item.queue_item_id)
                return url

        if not self._base:
            logger.error(
                "stream_base_url is not configured — cannot build a public stream URL."
            )
            # Fall back to the raw URI so debugging is possible; Alexa will
            # likely reject this.
            return item.uri or ""

        # Build a proxy path:  {stream_base_url}/stream/{queue_id}/{item_id}
        path = f"/stream/{quote(item.queue_id, safe='')}/{quote(item.queue_item_id, safe='')}"
        public_url = urljoin(self._base + "/", path.lstrip("/"))
        logger.debug("Resolved stream URL: %s", public_url)
        return public_url
