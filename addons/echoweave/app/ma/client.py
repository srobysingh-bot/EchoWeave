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

    def _api_endpoint(self) -> str:
        if self._base_url.endswith("/api"):
            return self._base_url
        return f"{self._base_url}/api"

    async def _post_command(self, command: str, **payload: Any) -> Any:
        """Call MA command API via POST /api with command payload."""
        client = await self._ensure_client()
        endpoint = self._api_endpoint()
        body: dict[str, Any] = {"command": command}
        body.update(payload)

        logger.info("MA API request: url=%s command=%s", endpoint, command)
        try:
            resp = await client.post(endpoint, json=body)
            logger.info(
                "MA API response: url=%s command=%s status=%s",
                endpoint,
                command,
                resp.status_code,
            )
            resp.raise_for_status()
            data = resp.json()
            if isinstance(data, dict) and "result" in data:
                return data["result"]
            return data
        except httpx.ConnectError as exc:
            logger.warning("MA API connect error: url=%s command=%s", endpoint, command)
            raise MusicAssistantUnreachableError(
                f"Cannot reach MA server at {self._base_url}"
            ) from exc
        except httpx.TimeoutException as exc:
            logger.warning("MA API timeout: url=%s command=%s", endpoint, command)
            raise MusicAssistantUnreachableError(
                f"MA request timed out for {endpoint}"
            ) from exc
        except httpx.HTTPStatusError as exc:
            status = exc.response.status_code
            logger.warning(
                "MA API status error: url=%s command=%s status=%s",
                endpoint,
                command,
                status,
            )
            if status == 401:
                raise MusicAssistantAuthError("MA token rejected (401).") from exc
            raise MusicAssistantError(
                f"MA API error: {status} (command={command}, url={endpoint})"
            ) from exc

    # -- public API ----------------------------------------------------------

    async def ping(self) -> bool:
        """Return ``True`` if the MA server responds to a health probe."""
        try:
            await self._post_command("players/all")
            return True
        except MusicAssistantAuthError:
            # Reachable but token rejected: connectivity is still OK.
            return True
        except MusicAssistantError:
            return False
        except Exception:
            return False

    async def get_server_info(self) -> MAServerInfo:
        """Fetch basic server information from MA."""
        data = await self._post_command("server/info")
        return MAServerInfo.model_validate(data)

    async def validate_token(self) -> bool:
        """Return ``True`` if our bearer token is accepted by MA."""
        try:
            await self._post_command("players/all")
            return True
        except MusicAssistantAuthError:
            return False

    async def get_players(self) -> list[dict[str, Any]]:
        """Return the list of players known to MA."""
        data = await self._post_command("players/all")
        if isinstance(data, list):
            return data
        raise MusicAssistantError("MA API error: unexpected players/all response shape")

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

    async def _resolve_default_queue_id(self) -> str | None:
        players = await self.get_players()
        for player in players:
            active_queue = player.get("active_queue") or player.get("active_source")
            if active_queue:
                return str(active_queue)
        return None

    async def get_queue_state(self, queue_id: str | None = None) -> dict[str, Any]:
        resolved_queue_id = queue_id or await self._resolve_default_queue_id()
        if not resolved_queue_id:
            raise MusicAssistantError("No active queue available.")

        resp = await self._get(f"/api/player_queues/{resolved_queue_id}")
        data = resp.json()
        return {
            "queue_id": resolved_queue_id,
            "state": data.get("state", "unknown"),
            "elapsed_time": data.get("elapsed_time", 0),
            "current_item": data.get("current_item", {}),
            "next_item": data.get("next_item", {}),
        }

    def get_item_metadata(self, item: MAQueueItem | None) -> dict[str, Any]:
        if not item:
            return {}
        return {
            "queue_id": item.queue_id,
            "queue_item_id": item.queue_item_id,
            "title": item.name,
            "subtitle": item.artist or item.album,
            "artist": item.artist,
            "album": item.album,
            "image_url": item.image_url,
            "duration": item.duration,
            "uri": item.uri,
        }

    async def build_stream_context(self, queue_id: str, queue_item_id: str) -> dict[str, Any]:
        source_url = await self.get_stream_url(queue_id, queue_item_id)
        if not source_url:
            raise MusicAssistantError("No stream source resolved for queue item.")
        return {
            "queue_id": queue_id,
            "queue_item_id": queue_item_id,
            "source_url": source_url,
            "content_type": "audio/mpeg",
        }

    async def get_current_playable_item(self, queue_id: str | None = None) -> Optional[dict[str, Any]]:
        resolved_queue_id = queue_id or await self._resolve_default_queue_id()
        if not resolved_queue_id:
            return None

        item = await self.get_current_queue_item(resolved_queue_id)
        if not item:
            return None

        stream_ctx = await self.build_stream_context(resolved_queue_id, item.queue_item_id)
        metadata = self.get_item_metadata(item)
        return {
            **metadata,
            "origin_stream_path": f"/edge/stream/{resolved_queue_id}/{item.queue_item_id}",
            "content_type": stream_ctx.get("content_type", "audio/mpeg"),
        }

    async def get_next_playable_item(self, queue_id: str | None = None) -> Optional[dict[str, Any]]:
        resolved_queue_id = queue_id or await self._resolve_default_queue_id()
        if not resolved_queue_id:
            return None

        item = await self.get_next_queue_item(resolved_queue_id)
        if not item:
            return None

        stream_ctx = await self.build_stream_context(resolved_queue_id, item.queue_item_id)
        metadata = self.get_item_metadata(item)
        return {
            **metadata,
            "origin_stream_path": f"/edge/stream/{resolved_queue_id}/{item.queue_item_id}",
            "content_type": stream_ctx.get("content_type", "audio/mpeg"),
        }

    async def resolve_play_request(self, queue_id: str | None = None) -> dict[str, Any]:
        playable = await self.get_current_playable_item(queue_id)
        if playable:
            return playable

        playable = await self.get_next_playable_item(queue_id)
        if playable:
            return playable

        raise MusicAssistantError("No playable queue item available.")

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

    async def execute_play_command(self, queue_id: str | None = None) -> tuple[bool, str]:
        """Attempt to start/resume playback through MA command API.

        Returns ``(success, message)`` for connector acknowledgment.
        """
        try:
            target_queue_id = queue_id
            players = await self.get_players()

            if not target_queue_id:
                for player in players:
                    active_queue = player.get("active_queue") or player.get("active_source")
                    if active_queue:
                        target_queue_id = str(active_queue)
                        break

            if target_queue_id:
                await self._post_command("player_queues/play", queue_id=target_queue_id)
                return True, f"play-started queue_id={target_queue_id}"

            for player in players:
                player_id = player.get("player_id")
                if not player_id:
                    continue
                try:
                    await self._post_command("players/cmd/play", player_id=player_id)
                    return True, f"play-started player_id={player_id}"
                except MusicAssistantError:
                    continue

            return False, "no-player-or-queue"
        except MusicAssistantAuthError:
            return False, "ma-auth-failed"
        except MusicAssistantUnreachableError:
            return False, "ma-unreachable"
        except MusicAssistantError as exc:
            return False, f"ma-error:{exc}"
