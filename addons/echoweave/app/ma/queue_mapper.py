"""Translate Music Assistant queue semantics into Alexa playback semantics."""

from __future__ import annotations

import logging
from typing import Optional

from app.ma.client import MusicAssistantClient
from app.ma.models import MAQueueItem
from app.ma.stream_resolver import StreamResolver

logger = logging.getLogger(__name__)


class QueueMapper:
    """Bridge between MA queue items and Alexa-compatible playback info.

    This mapper fetches current/next items from MA and pairs them with
    externally-reachable stream URLs via ``StreamResolver``.
    """

    def __init__(self, ma_client: MusicAssistantClient, stream_resolver: StreamResolver) -> None:
        self._ma = ma_client
        self._resolver = stream_resolver

    async def get_current_track_for_alexa(
        self,
        queue_id: str,
    ) -> Optional[dict]:
        """Return the current track in an Alexa-friendly dict, or ``None``.

        Keys: ``token``, ``url``, ``name``, ``artist``, ``offset_ms``.
        """
        item = await self._ma.get_current_queue_item(queue_id)
        if item is None:
            return None
        return await self._to_alexa_track(item)

    async def get_next_track_for_alexa(
        self,
        queue_id: str,
    ) -> Optional[dict]:
        """Return the next queued track in Alexa-friendly dict, or ``None``."""
        item = await self._ma.get_next_queue_item(queue_id)
        if item is None:
            return None
        return await self._to_alexa_track(item)

    async def _to_alexa_track(self, item: MAQueueItem) -> dict:
        stream_url = self._resolver.resolve(item)
        return {
            "token": f"ma:{item.queue_id}:{item.queue_item_id}",
            "url": stream_url,
            "name": item.name,
            "artist": item.artist,
            "offset_ms": 0,
        }
