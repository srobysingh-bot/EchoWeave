"""Async Music Assistant API client.

Handles health checks, auth validation, queue/stream resolution, and
server-info retrieval.  Uses ``httpx.AsyncClient`` with retry logic and
structured error handling.
"""

from __future__ import annotations

import logging
from typing import Any, Optional

import httpx

from app.core.exceptions import (
    MusicAssistantAuthError,
    MusicAssistantError,
    MusicAssistantUnreachableError,
)
from app.ma.auth import build_auth_headers
from app.ma.models import MAServerInfo, MAQueueItem

logger = logging.getLogger(__name__)

_DEFAULT_TIMEOUT = 15.0
_MAX_RETRIES = 2


class MusicAssistantClient:
    """Async client for the Music Assistant REST/WebSocket API.

    Parameters
    ----------
    base_url:
        Root URL of the MA server, e.g. ``http://192.168.1.42:8095``.
    token:
        Long-lived bearer token.
    timeout:
        Default HTTP request timeout in seconds.
    """

    def __init__(
        self,
        base_url: str,
        token: str,
        *,
        timeout: float = _DEFAULT_TIMEOUT,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._token = token
        self._timeout = timeout
        self._client: httpx.AsyncClient | None = None

    # -- lifecycle -----------------------------------------------------------

    async def _ensure_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                base_url=self._base_url,
                headers=build_auth_headers(self._token),
                timeout=self._timeout,
            )
        return self._client

    async def close(self) -> None:
        """Close the underlying HTTP client."""
        if self._client and not self._client.is_closed:
            await self._client.aclose()
            self._client = None

    # -- low-level request ---------------------------------------------------

    async def _get(self, path: str, **kwargs: Any) -> httpx.Response:
        client = await self._ensure_client()
        last_exc: Exception | None = None
        for attempt in range(1, _MAX_RETRIES + 1):
            try:
                resp = await client.get(path, **kwargs)
                resp.raise_for_status()
                return resp
            except httpx.ConnectError as exc:
                last_exc = exc
                logger.warning("MA connection attempt %d failed: %s", attempt, exc)
            except httpx.HTTPStatusError as exc:
                if exc.response.status_code == 401:
                    raise MusicAssistantAuthError("MA token rejected (401).") from exc
                raise MusicAssistantError(
                    f"MA API error: {exc.response.status_code}"
                ) from exc
            except httpx.TimeoutException as exc:
                last_exc = exc
                logger.warning("MA request timed out (attempt %d).", attempt)
        raise MusicAssistantUnreachableError(
            f"Could not reach MA server at {self._base_url} after {_MAX_RETRIES} attempts."
        ) from last_exc

    async def _post(self, path: str, **kwargs: Any) -> httpx.Response:
        client = await self._ensure_client()
        try:
            resp = await client.post(path, **kwargs)
            resp.raise_for_status()
            return resp
        except httpx.ConnectError as exc:
            raise MusicAssistantUnreachableError(
                f"Cannot reach MA server at {self._base_url}"
            ) from exc
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == 401:
                raise MusicAssistantAuthError("MA token rejected (401).") from exc
            raise MusicAssistantError(
                f"MA API error: {exc.response.status_code}"
            ) from exc

    # -- public API ----------------------------------------------------------

    async def ping(self) -> bool:
        """Return ``True`` if the MA server responds to a health probe."""
        try:
            await self._get("/api")
            return True
        except MusicAssistantError:
            return False
        except Exception:
            return False

    async def get_server_info(self) -> MAServerInfo:
        """Fetch basic server information from MA."""
        resp = await self._get("/api")
        data = resp.json()
        return MAServerInfo.model_validate(data)

    async def validate_token(self) -> bool:
        """Return ``True`` if our bearer token is accepted by MA."""
        try:
            await self._get("/api/players")
            return True
        except MusicAssistantAuthError:
            return False

    async def get_players(self) -> list[dict[str, Any]]:
        """Return the list of players known to MA."""
        resp = await self._get("/api/players")
        return resp.json()

    async def get_queue_items(self, queue_id: str) -> list[MAQueueItem]:
        """Return items in the specified MA queue."""
        resp = await self._get(f"/api/player_queues/{queue_id}/items")
        items = resp.json()
        return [MAQueueItem.model_validate(item) for item in items]

    async def get_current_queue_item(self, queue_id: str) -> Optional[MAQueueItem]:
        """Return the currently-playing queue item, or ``None``."""
        resp = await self._get(f"/api/player_queues/{queue_id}")
        data = resp.json()
        current = data.get("current_item")
        if current:
            return MAQueueItem.model_validate(current)
        return None

    async def get_next_queue_item(self, queue_id: str) -> Optional[MAQueueItem]:
        """Return the next queue item, or ``None`` if queue is exhausted."""
        resp = await self._get(f"/api/player_queues/{queue_id}")
        data = resp.json()
        next_item = data.get("next_item")
        if next_item:
            return MAQueueItem.model_validate(next_item)
        return None

    async def get_stream_url(self, queue_id: str, item_id: str) -> str | None:
        """Resolve a playable stream URL from MA for the given queue item.

        Returns ``None`` if no URL can be resolved.
        """
        # TODO: Confirm the exact MA API path for stream resolution once
        # integrated with a live MA instance.
        try:
            resp = await self._get(f"/api/player_queues/{queue_id}/items/{item_id}")
            data = resp.json()
            return data.get("streamdetails", {}).get("url") or data.get("uri")
        except MusicAssistantError:
            logger.warning("Stream resolution failed for item %s in queue %s", item_id, queue_id)
            return None
