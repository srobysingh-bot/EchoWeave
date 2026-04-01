"""Async Music Assistant API client.

Handles health checks, auth validation, queue/stream resolution, and
server-info retrieval.  Uses ``httpx.AsyncClient`` with retry logic and
structured error handling.
"""

from __future__ import annotations

import logging
import json
import re
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
                logger.info("MA API request: method=GET path=%s", path)
                resp = await client.get(path, **kwargs)
                logger.info(
                    "MA API response: method=GET path=%s status=%s",
                    path,
                    resp.status_code,
                )
                resp.raise_for_status()
                return resp
            except httpx.ConnectError as exc:
                last_exc = exc
                logger.warning("MA connection attempt %d failed: %s", attempt, exc)
            except httpx.HTTPStatusError as exc:
                status = exc.response.status_code
                body = (exc.response.text or "")[:2000]
                logger.warning(
                    "MA API status error: method=GET path=%s status=%s body=%s",
                    path,
                    status,
                    body,
                )
                if exc.response.status_code == 401:
                    raise MusicAssistantAuthError("MA token rejected (401).") from exc
                raise MusicAssistantError(
                    f"MA API error: {exc.response.status_code} (method=GET path={path} body={body})"
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

        logger.info(
            "MA API request: method=POST path=%s command=%s payload=%s",
            endpoint,
            command,
            json.dumps(payload, separators=(",", ":"), default=str),
        )
        try:
            resp = await client.post(endpoint, json=body)
            logger.info(
                "MA API response: method=POST path=%s command=%s status=%s",
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
            body_text = (exc.response.text or "")[:2000]
            payload_text = json.dumps(payload, separators=(",", ":"), default=str)
            logger.warning(
                "MA API status error: method=POST path=%s command=%s status=%s body=%s",
                endpoint,
                command,
                status,
                body_text,
            )
            if status == 401:
                raise MusicAssistantAuthError("MA token rejected (401).") from exc
            raise MusicAssistantError(
                f"MA API error: {status} (method=POST path={endpoint} command={command} payload={payload_text} body={body_text})"
            ) from exc

    def _queue_paths(self, queue_id: str, suffix: str = "") -> list[str]:
        normalized_queue_id = self._sanitize_queue_id(queue_id, source="queue_paths")
        if not normalized_queue_id:
            raise MusicAssistantError("Invalid or stale queue id rejected before MA queue GET.")
        # MA versions differ in queue REST route naming; try both variants.
        return [
            f"/api/player_queues/{normalized_queue_id}{suffix}",
            f"/api/playerqueues/{normalized_queue_id}{suffix}",
        ]

    async def _get_with_path_fallback(self, paths: list[str]) -> httpx.Response:
        last_error: MusicAssistantError | None = None
        for idx, path in enumerate(paths):
            try:
                resp = await self._get(path)
                if idx > 0:
                    logger.info("MA API fallback path succeeded: method=GET path=%s", path)
                return resp
            except MusicAssistantError as exc:
                last_error = exc
                # Retry only for 404 on alternate path candidates.
                if "MA API error: 404" in str(exc) and idx < len(paths) - 1:
                    logger.warning("MA API 404 for path=%s; retrying alternate queue path", path)
                    continue
                raise
        if last_error:
            raise last_error
        raise MusicAssistantError("MA API fallback failed: no paths attempted")

    async def _post_command_with_fallback(self, commands: list[str], **payload: Any) -> Any:
        last_error: MusicAssistantError | None = None
        for idx, command in enumerate(commands):
            try:
                result = await self._post_command(command, **payload)
                if idx > 0:
                    logger.info("MA API fallback command succeeded: command=%s", command)
                return result
            except MusicAssistantError as exc:
                last_error = exc
                # Retry only for 404 on alternate command names.
                if "MA API error: 404" in str(exc) and idx < len(commands) - 1:
                    logger.warning("MA API 404 for command=%s; retrying alternate command", command)
                    continue
                raise
        if last_error:
            raise last_error
        raise MusicAssistantError("MA API fallback failed: no commands attempted")

    def _is_stale_numeric_queue_id(self, queue_id: str) -> bool:
        return bool(re.fullmatch(r"-?\d+", queue_id.strip()))

    def _sanitize_queue_id(self, queue_id: str | None, *, source: str) -> str | None:
        if queue_id is None:
            return None
        normalized = str(queue_id).strip()
        if not normalized:
            return None
        if self._is_stale_numeric_queue_id(normalized):
            logger.warning(
                "Discarding queue_id=%s source=%s reason=stale_numeric_queue_id",
                normalized,
                source,
            )
            return None
        return normalized

    def _is_queue_not_found(self, exc: MusicAssistantError) -> bool:
        return "MA API error: 404" in str(exc)

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

    async def get_queue_items(self, queue_id: str, *, request_id: str = "", home_id: str = "", player_id: str = "") -> list[MAQueueItem]:
        """Return items in the specified MA queue."""
        resp = await self._get_with_path_fallback(self._queue_paths(queue_id, "/items"))
        items = resp.json()
        logger.info(json.dumps({
            "event": "ma_get_queue_items",
            "request_id": request_id,
            "home_id": home_id,
            "player_id": player_id,
            "queue_id": queue_id,
            "num_items": len(items),
        }))
        return [MAQueueItem.model_validate(item) for item in items]

    async def get_queue_item(self, queue_id: str, queue_item_id: str, *, request_id: str = "", home_id: str = "", player_id: str = "") -> Optional[MAQueueItem]:
        """Return a specific queue item by id, or ``None`` if unavailable."""
        try:
            resp = await self._get_with_path_fallback(
                self._queue_paths(queue_id, f"/items/{queue_item_id}"),
            )
            data = resp.json()
            if isinstance(data, dict):
                logger.info(json.dumps({
                    "event": "ma_get_queue_item",
                    "request_id": request_id,
                    "home_id": home_id,
                    "player_id": player_id,
                    "queue_id": queue_id,
                    "queue_item_id": queue_item_id,
                    "found": True,
                }))
                return MAQueueItem.model_validate(data)
        except MusicAssistantError:
            logger.warning(json.dumps({
                "event": "ma_get_queue_item_failed",
                "request_id": request_id,
                "home_id": home_id,
                "player_id": player_id,
                "queue_id": queue_id,
                "queue_item_id": queue_item_id,
                "found": False,
            }))
        return None

    async def get_current_queue_item(self, queue_id: str) -> Optional[MAQueueItem]:
        """Return the currently-playing queue item, or ``None``."""
        resp = await self._get_with_path_fallback(self._queue_paths(queue_id))
        data = resp.json()
        current = data.get("current_item")
        if current:
            return MAQueueItem.model_validate(current)
        return None

    async def get_next_queue_item(self, queue_id: str) -> Optional[MAQueueItem]:
        """Return the next queue item, or ``None`` if queue is exhausted."""
        resp = await self._get_with_path_fallback(self._queue_paths(queue_id))
        data = resp.json()
        next_item = data.get("next_item")
        if next_item:
            return MAQueueItem.model_validate(next_item)
        return None

    async def _resolve_default_queue_id(self) -> str | None:
        players = await self.get_players()
        for player in players:
            player_id = str(player.get("player_id") or "")
            candidates = [
                ("active_queue", player.get("active_queue")),
                ("active_source", player.get("active_source")),
                ("queue_id", player.get("queue_id")),
            ]
            for candidate_source, candidate in candidates:
                if not candidate:
                    continue
                queue_id = str(candidate).strip()
                if not queue_id:
                    continue
                if self._is_stale_numeric_queue_id(queue_id):
                    logger.warning(
                        "MA queue candidate rejected queue_id=%s player_id=%s candidate_source=%s reason=stale_numeric_queue_id",
                        queue_id,
                        player_id,
                        candidate_source,
                    )
                    continue
                try:
                    # Validate candidate queue id before selecting it; stale queue ids can
                    # linger in player state and cause hard 404 lookup failures.
                    await self._get_with_path_fallback(self._queue_paths(queue_id))
                    logger.info(
                        "MA queue auto-discovery selected queue_id=%s player_id=%s candidate_source=%s",
                        queue_id,
                        player_id,
                        candidate_source,
                    )
                    return queue_id
                except MusicAssistantError as exc:
                    logger.warning(
                        "MA queue candidate rejected queue_id=%s player_id=%s candidate_source=%s error=%s",
                        queue_id,
                        player_id,
                        candidate_source,
                        str(exc),
                    )
                    continue
        logger.warning("MA queue auto-discovery found no active queue")
        return None

    async def get_queue_state(self, queue_id: str | None = None) -> dict[str, Any]:
        requested_queue_id = self._sanitize_queue_id(queue_id, source="get_queue_state.request")
        resolved_queue_id = requested_queue_id or await self._resolve_default_queue_id()
        if not resolved_queue_id:
            raise MusicAssistantError("No active queue available.")

        try:
            resp = await self._get_with_path_fallback(self._queue_paths(resolved_queue_id))
        except MusicAssistantError as exc:
            if requested_queue_id and self._is_queue_not_found(exc):
                logger.warning(
                    "get_queue_state requested queue_id=%s returned 404; discarding and re-resolving active queue",
                    requested_queue_id,
                )
                resolved_queue_id = await self._resolve_default_queue_id()
                if not resolved_queue_id:
                    raise MusicAssistantError("No active queue available.") from exc
                resp = await self._get_with_path_fallback(self._queue_paths(resolved_queue_id))
            else:
                raise
        data = resp.json()
        return {
            "queue_id": resolved_queue_id,
            "state": data.get("state", "unknown"),
            "elapsed_time": data.get("elapsed_time", 0),
            "current_item": data.get("current_item", {}),
            "next_item": data.get("next_item", {}),
        }

    async def _select_queue_item(self, queue_id: str, *, prefer_current: bool) -> Optional[MAQueueItem]:
        if prefer_current:
            item = await self.get_current_queue_item(queue_id)
            if item:
                return item
            return await self.get_next_queue_item(queue_id)

        item = await self.get_next_queue_item(queue_id)
        if item:
            return item
        return await self.get_current_queue_item(queue_id)

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
            "origin_stream_path": f"/edge/stream/{queue_id}/{queue_item_id}",
            "content_type": "audio/mpeg",
        }

    async def get_current_playable_item(self, queue_id: str | None = None, *, request_id: str = "", home_id: str = "", player_id: str = "") -> Optional[dict[str, Any]]:
        requested_queue_id = self._sanitize_queue_id(queue_id, source="get_current_playable_item.request")
        resolved_queue_id = requested_queue_id or await self._resolve_default_queue_id()
        if not resolved_queue_id:
            logger.info(json.dumps({
                "event": "ma_no_queue_id",
                "request_id": request_id,
                "home_id": home_id,
                "player_id": player_id,
                "requested_queue_id": queue_id,
                "reason": "no_resolved_queue_id"
            }))
            return None

        try:
            item = await self._select_queue_item(resolved_queue_id, prefer_current=True)
        except MusicAssistantError as exc:
            if requested_queue_id and self._is_queue_not_found(exc):
                logger.warning(json.dumps({
                    "event": "ma_queue_404",
                    "request_id": request_id,
                    "home_id": home_id,
                    "player_id": player_id,
                    "queue_id": requested_queue_id,
                    "reason": "queue_404"
                }))
                resolved_queue_id = await self._resolve_default_queue_id()
                if not resolved_queue_id:
                    return None
                item = await self._select_queue_item(resolved_queue_id, prefer_current=True)
            else:
                raise
        if not item:
            logger.info(json.dumps({
                "event": "ma_no_playable_item",
                "request_id": request_id,
                "home_id": home_id,
                "player_id": player_id,
                "queue_id": resolved_queue_id,
                "reason": "no_current_playable_item"
            }))
            return None

        stream_ctx = await self.build_stream_context(resolved_queue_id, item.queue_item_id)
        metadata = self.get_item_metadata(item)
        logger.info(json.dumps({
            "event": "ma_selected_current_playable_item",
            "request_id": request_id,
            "home_id": home_id,
            "player_id": player_id,
            "queue_id": resolved_queue_id,
            "queue_item_id": item.queue_item_id,
            "title": item.name,
            "origin_stream_path": stream_ctx["origin_stream_path"]
        }))
        return {
            **metadata,
            "origin_stream_path": stream_ctx["origin_stream_path"],
            "content_type": stream_ctx.get("content_type", "audio/mpeg"),
        }

    async def get_next_playable_item(self, queue_id: str | None = None, *, request_id: str = "", home_id: str = "", player_id: str = "") -> Optional[dict[str, Any]]:
        requested_queue_id = self._sanitize_queue_id(queue_id, source="get_next_playable_item.request")
        resolved_queue_id = requested_queue_id or await self._resolve_default_queue_id()
        if not resolved_queue_id:
            logger.info(json.dumps({
                "event": "ma_no_queue_id",
                "request_id": request_id,
                "home_id": home_id,
                "player_id": player_id,
                "requested_queue_id": queue_id,
                "reason": "no_resolved_queue_id"
            }))
            return None

        try:
            item = await self._select_queue_item(resolved_queue_id, prefer_current=False)
        except MusicAssistantError as exc:
            if requested_queue_id and self._is_queue_not_found(exc):
                logger.warning(json.dumps({
                    "event": "ma_queue_404",
                    "request_id": request_id,
                    "home_id": home_id,
                    "player_id": player_id,
                    "queue_id": requested_queue_id,
                    "reason": "queue_404"
                }))
                resolved_queue_id = await self._resolve_default_queue_id()
                if not resolved_queue_id:
                    return None
                item = await self._select_queue_item(resolved_queue_id, prefer_current=False)
            else:
                raise
        if not item:
            logger.info(json.dumps({
                "event": "ma_no_playable_item",
                "request_id": request_id,
                "home_id": home_id,
                "player_id": player_id,
                "queue_id": resolved_queue_id,
                "reason": "no_next_playable_item"
            }))
            return None

        stream_ctx = await self.build_stream_context(resolved_queue_id, item.queue_item_id)
        metadata = self.get_item_metadata(item)
        logger.info(json.dumps({
            "event": "ma_selected_next_playable_item",
            "request_id": request_id,
            "home_id": home_id,
            "player_id": player_id,
            "queue_id": resolved_queue_id,
            "queue_item_id": item.queue_item_id,
            "title": item.name,
            "origin_stream_path": stream_ctx["origin_stream_path"]
        }))
        return {
            **metadata,
            "origin_stream_path": stream_ctx["origin_stream_path"],
            "content_type": stream_ctx.get("content_type", "audio/mpeg"),
        }

    async def resolve_play_request(self, queue_id: str | None = None, *, request_id: str = "", home_id: str = "", player_id: str = "") -> dict[str, Any]:
        requested_queue_id = self._sanitize_queue_id(queue_id, source="resolve_play_request.request")
        log_ctx = {
            "event": "ma_resolve_play_request",
            "request_id": request_id,
            "home_id": home_id,
            "player_id": player_id,
            "requested_queue_id": queue_id,
        }

        playable: dict[str, Any] | None = None
        if requested_queue_id:
            try:
                playable = await self.get_current_playable_item(requested_queue_id, request_id=request_id, home_id=home_id, player_id=player_id)
            except MusicAssistantError as exc:
                if self._is_queue_not_found(exc):
                    logger.warning(json.dumps({**log_ctx, "reason": "queue_not_found"}))
                    requested_queue_id = None
                else:
                    logger.warning(json.dumps({**log_ctx, "reason": "exception", "details": str(exc)}))
                    raise

        if playable:
            logger.info(json.dumps({**log_ctx, "result": "current_playable", "queue_id": playable.get("queue_id"), "queue_item_id": playable.get("queue_item_id") }))
            return playable

        if requested_queue_id:
            playable = await self.get_next_playable_item(requested_queue_id, request_id=request_id, home_id=home_id, player_id=player_id)
            if playable:
                logger.info(json.dumps({**log_ctx, "result": "next_playable", "queue_id": playable.get("queue_id"), "queue_item_id": playable.get("queue_item_id") }))
                return playable

        playable = await self.get_current_playable_item(None, request_id=request_id, home_id=home_id, player_id=player_id)
        if playable:
            logger.info(json.dumps({**log_ctx, "result": "fallback_current_playable", "queue_id": playable.get("queue_id"), "queue_item_id": playable.get("queue_item_id") }))
            return playable

        playable = await self.get_next_playable_item(None, request_id=request_id, home_id=home_id, player_id=player_id)
        if playable:
            logger.info(json.dumps({**log_ctx, "result": "fallback_next_playable", "queue_id": playable.get("queue_id"), "queue_item_id": playable.get("queue_item_id") }))
            return playable

        logger.warning(json.dumps({**log_ctx, "result": "no_playable_item", "reason": "queue_empty"}))
        raise MusicAssistantError(json.dumps({"code": "queue_empty", "message": "No playable queue item available."}))

    async def get_stream_url(self, queue_id: str, item_id: str) -> str | None:
        """Resolve a playable stream URL from MA for the given queue item.

        Returns ``None`` if no URL can be resolved.
        """
        # TODO: Confirm the exact MA API path for stream resolution once
        # integrated with a live MA instance.
        try:
            item = await self.get_queue_item(queue_id, item_id)
            if item and item.streamdetails and item.streamdetails.url:
                return item.streamdetails.url
            if item and item.uri:
                return item.uri

            # Fallback: command-based stream resolution in newer MA builds.
            result = await self._post_command_with_fallback(
                ["player_queues/get_stream_url", "playerqueues/get_stream_url"],
                queue_id=queue_id,
                queue_item_id=item_id,
            )
            if isinstance(result, str) and result:
                return result
            if isinstance(result, dict):
                return str(result.get("url") or "") or None
        except MusicAssistantError:
            logger.warning("Stream resolution failed for item %s in queue %s", item_id, queue_id)
            return None

    async def execute_play_command(self, queue_id: str | None = None) -> tuple[bool, str]:
        """Attempt to start/resume playback through MA command API.

        Returns ``(success, message)`` for connector acknowledgment.
        """
        try:
            target_queue_id = self._sanitize_queue_id(queue_id, source="execute_play_command.request")
            players = await self.get_players()

            if not target_queue_id:
                for player in players:
                    active_queue = player.get("active_queue") or player.get("active_source")
                    if active_queue:
                        candidate_queue_id = self._sanitize_queue_id(
                            str(active_queue),
                            source=f"execute_play_command.player:{player.get('player_id')}",
                        )
                        if candidate_queue_id:
                            target_queue_id = candidate_queue_id
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
