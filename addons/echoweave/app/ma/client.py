"""Async Music Assistant API client.

Handles health checks, auth validation, queue/stream resolution, and
server-info retrieval.  Uses ``httpx.AsyncClient`` with retry logic and
structured error handling.
"""

from __future__ import annotations

import asyncio
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

# ── Session-ID resolution ────────────────────────────────────────────
# MA's PlayerQueue.session_id has serialize="omit", so it never appears
# in API responses.  We extract it from Player.current_media.custom_data
# (set when a previous play happened via MA UI) and cache it here.
#
# IMPORTANT: We never call play_index ourselves.  play_index sets
# queue.session_id to a new random value that we can't read back
# (serialize="omit"), and if _load_item fails the 500 leaves
# session_id permanently corrupted.  When session_id is None
# (fresh start / MA restart), the stream server skips the check
# entirely — any session value works.
_ma_session_cache: dict[str, tuple[str, float]] = {}
_MA_SESSION_CACHE_TTL = 600  # 10 minutes

import time as _time_mod


async def _prewarm_ma_stream_url(url: str) -> None:
    """Pre-warm MA's stream server by fetching response headers only.

    MA's ``serve_queue_item_stream`` resolves ``streamdetails`` *before*
    sending the HTTP 200 headers (it needs them to pick the output format).
    Connecting and reading just the headers therefore warms the in-memory
    ``queue_item.streamdetails`` cache, so the real Alexa fetch is instant.

    The connection is dropped after headers arrive; MA handles the
    ``BrokenPipeError`` / ``ConnectionResetError`` gracefully and logs nothing
    (because ``first_chunk_received`` is ``False`` at that point).
    """
    try:
        async with httpx.AsyncClient(
            timeout=httpx.Timeout(25.0, connect=5.0), follow_redirects=False
        ) as _client:
            async with _client.stream("GET", url) as _resp:
                logger.info(
                    "_prewarm_ma_stream_url: status=%d url=%s",
                    _resp.status_code, url,
                )
    except Exception as exc:
        # Pre-warm is best-effort — never let it affect the main flow.
        logger.debug("_prewarm_ma_stream_url: %s: %s", exc.__class__.__name__, exc)


def _get_cached_session_id(queue_id: str) -> str | None:
    entry = _ma_session_cache.get(queue_id)
    if entry:
        sid, ts = entry
        if _time_mod.time() - ts < _MA_SESSION_CACHE_TTL:
            return sid
        del _ma_session_cache[queue_id]
    return None


def _cache_session_id(queue_id: str, session_id: str) -> None:
    _ma_session_cache[queue_id] = (session_id, _time_mod.time())


def invalidate_session_cache(queue_id: str | None = None) -> None:
    """Clear cached session_id.  Called by stream_router on session 404."""
    if queue_id:
        _ma_session_cache.pop(queue_id, None)
    else:
        _ma_session_cache.clear()


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
        self._handoff_player_locks: dict[str, asyncio.Lock] = {}

    def _get_handoff_player_lock(self, player_id: str) -> asyncio.Lock:
        lock = self._handoff_player_locks.get(player_id)
        if lock is None:
            lock = asyncio.Lock()
            self._handoff_player_locks[player_id] = lock
        return lock

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
        message_id = str(int(__import__("time").time()))
        body = {
            "message_id": message_id,
            "command": command,
            "args": payload
        }

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
            response_text = exc.response.text or ""
            body_text = response_text if status >= 500 else response_text[:2000]
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
                # Retry on 404 (wrong command name) or 500 (command may differ
                # between MA versions) when there are more commands to try.
                err_str = str(exc)
                if idx < len(commands) - 1 and (
                    "MA API error: 404" in err_str or "MA API error: 500" in err_str
                ):
                    logger.warning("MA API error for command=%s; retrying alternate command", command)
                    continue
                raise
        if last_error:
            raise last_error
        raise MusicAssistantError("MA API fallback failed: no commands attempted")

    def _queue_commands(self, suffix: str = "") -> list[str]:
        # MA versions differ in namespace; try both variants.
        # Common ones are player_queues/items, playerqueues/items, etc.
        # But for 'get', we use the root player_queues/get.
        if suffix == "/items":
            return ["player_queues/items", "playerqueues/items"]
        return ["player_queues/get", "playerqueues/get", "player_queues/get_queue"]

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

    def _normalize_query(self, query: str | None) -> str:
        normalized = re.sub(r"\s+", " ", (query or "").strip().lower())
        normalized = re.sub(r"^(songs?|music)\s+by\s+", "", normalized)
        return normalized.strip()

    def _extract_search_items(self, data: Any, media_type: str) -> list[dict[str, Any]]:
        if isinstance(data, list):
            return [item for item in data if isinstance(item, dict)]

        if not isinstance(data, dict):
            return []

        singular = self._singular_media_type(media_type)
        keys = [media_type, singular, "items", "result", "results"]
        for key in keys:
            value = data.get(key)
            if isinstance(value, list):
                return [item for item in value if isinstance(item, dict)]

        nested = data.get("result")
        if isinstance(nested, dict):
            for key in (media_type, singular):
                value = nested.get(key)
                if isinstance(value, list):
                    return [item for item in value if isinstance(item, dict)]

        return []

    @staticmethod
    def _singular_media_type(media_type: str) -> str:
        """Convert plural media type to singular (e.g. 'tracks' -> 'track')."""
        mapping = {"tracks": "track", "artists": "artist", "albums": "album", "playlists": "playlist"}
        return mapping.get(media_type, media_type)

    async def _search_media(self, query: str, media_type: str, *, limit: int = 10) -> list[dict[str, Any]]:
        commands = ["music/search", "music.search"]
        singular = self._singular_media_type(media_type)
        payload_candidates: list[dict[str, Any]] = [
            {
                "search_query": query,
                "media_types": [singular],
                "limit": limit,
            },
            {
                "search_query": query,
                "media_types": [media_type],
                "limit": limit,
            },
            {
                "search": query,
                "media_types": [media_type],
                "limit": limit,
            },
            {
                "query": query,
                "media_types": [media_type],
                "limit": limit,
            },
            {
                "search": query,
                "media_type": media_type,
                "limit": limit,
            },
            {
                "query": query,
                "media_type": media_type,
                "limit": limit,
            },
        ]

        for payload in payload_candidates:
            try:
                result = await self._post_command_with_fallback(commands, **payload)
                items = self._extract_search_items(result, media_type)
                if items:
                    return items
            except MusicAssistantError:
                continue

        return []

    async def _resolve_player_id_for_queue(self, queue_id: str | None) -> str | None:
        effective_queue_id = self._sanitize_queue_id(queue_id, source="resolve_player_id_for_queue.queue")
        players = await self.get_players()

        if effective_queue_id:
            for player in players:
                player_id = str(player.get("player_id") or "").strip()
                if not player_id:
                    continue
                for candidate in (
                    player.get("active_queue"),
                    player.get("active_source"),
                    player.get("queue_id"),
                ):
                    candidate_queue_id = self._sanitize_queue_id(
                        str(candidate or ""),
                        source=f"resolve_player_id_for_queue.player:{player_id}",
                    )
                    if candidate_queue_id and candidate_queue_id == effective_queue_id:
                        return player_id

        # Prefer players that are online and likely capable of accepting play commands.
        for player in players:
            player_id = str(player.get("player_id") or "").strip()
            if player_id and self._is_player_play_capable(player):
                return player_id

        for player in players:
            player_id = str(player.get("player_id") or "").strip()
            if player_id:
                return player_id
        return None

    def _is_player_play_capable(self, player: dict[str, Any]) -> bool:
        available = bool(player.get("available", True))
        powered = bool(player.get("powered", True))
        state = str(player.get("state") or "").lower()
        if not available or not powered:
            return False
        if state in {"unavailable", "offline"}:
            return False
        return True

    def _player_inventory_snapshot(self, players: list[dict[str, Any]]) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        for player in players:
            current_media = player.get("current_media")
            media_preview: dict[str, str] = {}
            if isinstance(current_media, dict):
                media_preview = {
                    "title": str(current_media.get("title") or ""),
                    "artist": str(current_media.get("artist") or ""),
                    "uri": str(current_media.get("uri") or "")[:80],
                }
            out.append(
                {
                    "player_id": str(player.get("player_id") or ""),
                    "name": str(player.get("name") or ""),
                    "provider": str(player.get("provider") or player.get("source") or ""),
                    "available": bool(player.get("available", True)),
                    "powered": bool(player.get("powered", True)),
                    "state": str(player.get("state") or player.get("playback_state") or ""),
                    "active_queue": str(player.get("active_queue") or ""),
                    "active_source": str(player.get("active_source") or ""),
                    "queue_id": str(player.get("queue_id") or ""),
                    "has_current_media": current_media is not None,
                    "current_media": media_preview,
                }
            )
        return out

    async def _start_playback_for_playable(
        self,
        *,
        playable: dict[str, Any],
        payload_queue_id: str | None,
        request_id: str,
        home_id: str,
        requested_player_id: str,
        source: str,
    ) -> bool:
        effective_queue_id = self._sanitize_queue_id(
            str(playable.get("queue_id") or payload_queue_id or ""),
            source=f"start_playback_for_playable.{source}",
        )
        resolved_player_id = (requested_player_id or "").strip() or await self._resolve_player_id_for_queue(effective_queue_id)

        logger.warning(
            json.dumps(
                {
                    "event": "ma_playback_target_selection",
                    "request_id": request_id,
                    "home_id": home_id,
                    "source": source,
                    "queue_id": effective_queue_id,
                    "requested_player_id": requested_player_id,
                    "resolved_player_id": resolved_player_id,
                }
            )
        )

        start_attempts: list[tuple[list[str], dict[str, Any], str]] = []
        if effective_queue_id:
            start_attempts.append(
                (
                    ["player_queues/play", "playerqueues/play"],
                    {"queue_id": effective_queue_id},
                    "queue",
                )
            )
        if resolved_player_id:
            start_attempts.append(
                (
                    ["players/cmd/play"],
                    {"player_id": resolved_player_id},
                    "player",
                )
            )

        for start_commands, start_payload, start_target in start_attempts:
            try:
                logger.warning(
                    json.dumps(
                        {
                            "event": "ma_playback_start_attempt",
                            "request_id": request_id,
                            "home_id": home_id,
                            "player_id": resolved_player_id or requested_player_id,
                            "target": start_target,
                            "commands": start_commands,
                            "payload": start_payload,
                        }
                    )
                )
                start_response = await self._post_command_with_fallback(
                    start_commands,
                    **start_payload,
                )
                logger.warning(
                    json.dumps(
                        {
                            "event": "ma_playback_start_response",
                            "request_id": request_id,
                            "home_id": home_id,
                            "player_id": resolved_player_id or requested_player_id,
                            "target": start_target,
                            "response": start_response,
                        }
                    )
                )
                return True
            except MusicAssistantError as start_exc:
                logger.warning(
                    json.dumps(
                        {
                            "event": "ma_playback_start_attempt_failed",
                            "request_id": request_id,
                            "home_id": home_id,
                            "player_id": resolved_player_id or requested_player_id,
                            "target": start_target,
                            "payload": start_payload,
                            "error": str(start_exc),
                        }
                    )
                )

        logger.warning(
            json.dumps(
                {
                    "event": "ma_playback_start_failed_after_enqueue",
                    "request_id": request_id,
                    "home_id": home_id,
                    "player_id": resolved_player_id or requested_player_id,
                    "queue_id": playable.get("queue_id"),
                    "queue_item_id": playable.get("queue_item_id"),
                }
            )
        )
        return False

    async def _try_enqueue_search_result(
        self,
        item: dict[str, Any],
        *,
        media_type: str,
        queue_id: str | None,
        request_id: str,
        home_id: str,
        player_id: str,
        skip_playback_start: bool = False,
    ) -> dict[str, Any] | None:
        uri = str(item.get("uri") or "").strip()
        item_id = str(item.get("item_id") or item.get("id") or "").strip()
        if not uri and not item_id:
            logger.warning(
                json.dumps(
                    {
                        "event": "ma_enqueue_skip",
                        "request_id": request_id,
                        "home_id": home_id,
                        "player_id": player_id,
                        "reason": "no_uri_or_item_id",
                        "item_name": str(item.get("name") or ""),
                    }
                )
            )
            return None

        logger.warning(
            json.dumps(
                {
                    "event": "ma_resolved_media_object",
                    "request_id": request_id,
                    "home_id": home_id,
                    "player_id": player_id,
                    "media_type": media_type,
                    "queue_id": queue_id,
                    "item": {
                        "name": str(item.get("name") or ""),
                        "uri": uri,
                        "item_id": item_id,
                    },
                }
            )
        )

        # When skip_playback_start is True (Alexa flow):
        # Use option="play" so MA calls play_index internally, which resolves
        # JioSaavn/Alexa provider stream details.  We fire this and return
        # IMMEDIATELY — no sleep/wait here — so the Durable Object command
        # returns within the 8-second timeout.  MA runs play_index in the
        # background; when Alexa fetches the stream a few seconds later the
        # stream router reads the real session_id from current_media.
        if skip_playback_start:
            effective_uri = uri or f"library://{self._singular_media_type(media_type)}/{item_id}"
            # Resolve the actual MA player queue ID.
            synthetic_queue_id = queue_id or "default"
            try:
                real_ma_queue_id = await self._resolve_default_queue_id()
                if real_ma_queue_id:
                    synthetic_queue_id = real_ma_queue_id
                    logger.info(
                        "ma_skip_enqueue: resolved real MA queue_id=%s (was %s)",
                        real_ma_queue_id, queue_id,
                    )
            except Exception as _resolve_exc:
                logger.warning(
                    "ma_skip_enqueue: could not resolve MA queue_id, using %s: %s",
                    synthetic_queue_id, _resolve_exc,
                )

            synthetic_item_id = item_id or uri
            enqueue_ok = False
            if synthetic_queue_id and synthetic_queue_id != "default":
                media_candidates: list[str] = []
                if uri:
                    media_candidates.append(uri)
                if item_id:
                    singular = self._singular_media_type(media_type)
                    media_candidates.append(f"library://{singular}/{item_id}")
                if effective_uri and effective_uri not in media_candidates:
                    media_candidates.append(effective_uri)

                for media_candidate in media_candidates:
                    try:
                        await self._post_command_with_fallback(
                            ["player_queues/play_media", "players/play_media"],
                            queue_id=synthetic_queue_id,
                            media=media_candidate,
                            option="play",
                        )
                        logger.info(
                            json.dumps(
                                {
                                    "event": "ma_skip_enqueue_play_ok",
                                    "request_id": request_id,
                                    "home_id": home_id,
                                    "player_id": player_id,
                                    "queue_id": synthetic_queue_id,
                                    "media": media_candidate,
                                }
                            )
                        )
                        enqueue_ok = True
                        # Invalidate stale session_id cache — MA's play_index
                        # is now running in background and will set a new session_id.
                        invalidate_session_cache(synthetic_queue_id)  # module-level function
                        # Try to identify the queue_item_id MA assigned (fast,
                        # no waiting — we just read whatever is in the queue now).
                        try:
                            all_items = await self.get_queue_items(synthetic_queue_id)
                            for q_item in reversed(all_items):
                                q_uri = str(q_item.uri or "").strip()
                                q_name = str(q_item.name or "").strip().lower()
                                item_name = str(item.get("name") or "").strip().lower()
                                if (
                                    (q_uri and q_uri == media_candidate)
                                    or (q_uri and uri and q_uri == uri)
                                    or (q_item.queue_item_id == item_id)
                                    or (item_name and q_name and q_name == item_name)
                                ):
                                    synthetic_item_id = q_item.queue_item_id
                                    logger.info(
                                        json.dumps(
                                            {
                                                "event": "ma_skip_enqueue_item_matched",
                                                "request_id": request_id,
                                                "queue_id": synthetic_queue_id,
                                                "queue_item_id": synthetic_item_id,
                                                "matched_uri": q_uri,
                                                "matched_name": q_name,
                                            }
                                        )
                                    )
                                    break
                            else:
                                if all_items:
                                    synthetic_item_id = all_items[-1].queue_item_id
                                    logger.info(
                                        json.dumps(
                                            {
                                                "event": "ma_skip_enqueue_item_fallback_last",
                                                "request_id": request_id,
                                                "queue_id": synthetic_queue_id,
                                                "queue_item_id": synthetic_item_id,
                                                "total_items": len(all_items),
                                            }
                                        )
                                    )
                        except Exception as _items_exc:
                            logger.warning("ma_skip_enqueue: list queue items failed: %s", _items_exc)
                        break
                    except Exception as _enqueue_exc:
                        logger.warning(
                            json.dumps(
                                {
                                    "event": "ma_skip_enqueue_play_failed",
                                    "request_id": request_id,
                                    "home_id": home_id,
                                    "player_id": player_id,
                                    "queue_id": synthetic_queue_id,
                                    "media": media_candidate,
                                    "error": str(_enqueue_exc),
                                }
                            )
                        )
                        continue

            logger.warning(
                json.dumps(
                    {
                        "event": "ma_skip_enqueue_synthetic_playable",
                        "request_id": request_id,
                        "home_id": home_id,
                        "player_id": player_id,
                        "queue_id": synthetic_queue_id,
                        "queue_item_id": synthetic_item_id,
                        "uri": effective_uri,
                        "item_name": str(item.get("name") or ""),
                        "enqueue_ok": enqueue_ok,
                    }
                )
            )
            return {
                "queue_id": synthetic_queue_id,
                "queue_item_id": synthetic_item_id,
                "title": str(item.get("name") or ""),
                "subtitle": str(item.get("artist") or item.get("album") or ""),
                "artist": str(item.get("artist") or ""),
                "album": str(item.get("album") or ""),
                "image_url": str(item.get("image", {}).get("path", "") if isinstance(item.get("image"), dict) else item.get("image_url", "")),
                "duration": float(item.get("duration") or 0),
                "uri": effective_uri,
                "origin_stream_path": f"/edge/stream/{synthetic_queue_id}/{synthetic_item_id}",
                "content_type": "audio/mpeg",
            }

        payload_candidates: list[dict[str, Any]] = []
        # MA 2.x play_media expects: queue_id + media (uri string or list).
        # We try the URI first (preferred), then item_id-based URIs.
        if queue_id:
            if uri:
                payload_candidates.append({"queue_id": queue_id, "media": uri})
                payload_candidates.append({"queue_id": queue_id, "media": [uri]})
            if item_id:
                # Construct a library URI from media_type + item_id
                singular = self._singular_media_type(media_type)
                lib_uri = f"library://{singular}/{item_id}"
                payload_candidates.append({"queue_id": queue_id, "media": lib_uri})
                payload_candidates.append({"queue_id": queue_id, "media": [lib_uri]})
        # Fallback: try without queue_id (some MA versions auto-select)
        if uri:
            payload_candidates.append({"media": uri})
        if item_id:
            singular = self._singular_media_type(media_type)
            lib_uri = f"library://{singular}/{item_id}"
            payload_candidates.append({"media": lib_uri})

        playback_start_failed_observed = False
        for attempt, payload in enumerate(payload_candidates, 1):
            try:
                logger.warning(
                    json.dumps(
                        {
                            "event": "ma_playback_enqueue_attempt",
                            "request_id": request_id,
                            "home_id": home_id,
                            "player_id": player_id,
                            "attempt": attempt,
                            "payload": payload,
                        }
                    )
                )
                response = await self._post_command_with_fallback(
                    ["player_queues/play_media", "players/play_media"],
                    **payload,
                )
                logger.warning(
                    json.dumps(
                        {
                            "event": "ma_playback_enqueue_response",
                            "request_id": request_id,
                            "home_id": home_id,
                            "player_id": player_id,
                            "attempt": attempt,
                            "response": response,
                        }
                    )
                )
                playable = await self.get_current_playable_item(
                    queue_id,
                    request_id=request_id,
                    home_id=home_id,
                    player_id=player_id,
                )
                if playable:
                    logger.warning(
                        json.dumps(
                            {
                                "event": "ma_enqueue_success_current",
                                "request_id": request_id,
                                "home_id": home_id,
                                "player_id": player_id,
                                "queue_id": playable.get("queue_id"),
                                "queue_item_id": playable.get("queue_item_id"),
                                "item_name": str(playable.get("media_details", {}).get("title") or ""),
                            }
                        )
                    )
                    if skip_playback_start:
                        return playable
                    playback_started = await self._start_playback_for_playable(
                        playable=playable,
                        payload_queue_id=str(payload.get("queue_id") or "") or None,
                        request_id=request_id,
                        home_id=home_id,
                        requested_player_id=player_id,
                        source="current",
                    )
                    if playback_started:
                        return playable
                    playback_start_failed_observed = True
                playable = await self.get_next_playable_item(
                    queue_id,
                    request_id=request_id,
                    home_id=home_id,
                    player_id=player_id,
                )
                if playable:
                    logger.warning(
                        json.dumps(
                            {
                                "event": "ma_enqueue_success_next",
                                "request_id": request_id,
                                "home_id": home_id,
                                "player_id": player_id,
                                "queue_id": playable.get("queue_id"),
                                "queue_item_id": playable.get("queue_item_id"),
                                "item_name": str(playable.get("media_details", {}).get("title") or ""),
                            }
                        )
                    )
                    if skip_playback_start:
                        return playable
                    playback_started = await self._start_playback_for_playable(
                        playable=playable,
                        payload_queue_id=str(payload.get("queue_id") or "") or None,
                        request_id=request_id,
                        home_id=home_id,
                        requested_player_id=player_id,
                        source="next",
                    )
                    if playback_started:
                        return playable
                    playback_start_failed_observed = True
            except MusicAssistantError as exc:
                logger.warning(
                    json.dumps(
                        {
                            "event": "ma_enqueue_attempt_failed",
                            "request_id": request_id,
                            "home_id": home_id,
                            "player_id": player_id,
                            "attempt": attempt,
                            "error": str(exc),
                        }
                    )
                )
                continue

        if playback_start_failed_observed:
            logger.warning(
                json.dumps(
                    {
                        "event": "ma_playback_not_confirmed",
                        "request_id": request_id,
                        "home_id": home_id,
                        "player_id": player_id,
                        "item_name": str(item.get("name") or ""),
                    }
                )
            )
            raise MusicAssistantError(
                json.dumps(
                    {
                        "code": "play_start_failed",
                        "message": "Playback could not be started after enqueue.",
                    }
                )
            )
        
        logger.warning(
            json.dumps(
                {
                    "event": "ma_enqueue_all_attempts_failed",
                    "request_id": request_id,
                    "home_id": home_id,
                    "player_id": player_id,
                    "attempts": len(payload_candidates),
                    "item_name": str(item.get("name") or ""),
                }
            )
        )
        return None

    async def _resolve_query_play_request(
        self,
        *,
        query: str,
        queue_id: str | None,
        intent_name: str,
        request_id: str,
        home_id: str,
        player_id: str,
        skip_playback_start: bool = False,
    ) -> dict[str, Any] | None:
        normalized_query = self._normalize_query(query)
        if not normalized_query:
            return None

        # Ensure we have a queue_id — auto-discover if not provided.
        effective_queue_id = queue_id
        if not effective_queue_id:
            effective_queue_id = await self._resolve_default_queue_id()
            if effective_queue_id:
                logger.info(
                    "resolve_query_play_request: auto-discovered queue_id=%s for query=%s",
                    effective_queue_id,
                    normalized_query,
                )
            else:
                logger.warning(
                    "resolve_query_play_request: no queue_id available for query=%s",
                    normalized_query,
                )

        search_order = ["tracks", "artists", "albums", "playlists"]
        for media_type in search_order:
            results = await self._search_media(normalized_query, media_type)
            logger.warning(
                json.dumps(
                    {
                        "event": "ma_query_search",
                        "request_id": request_id,
                        "home_id": home_id,
                        "player_id": player_id,
                        "intent_name": intent_name,
                        "raw_query": query,
                        "normalized_query": normalized_query,
                        "media_type": media_type,
                        "results_count": len(results),
                        "result_preview": [
                            {
                                "name": str(item.get("name") or ""),
                                "uri": str(item.get("uri") or ""),
                                "item_id": str(item.get("item_id") or item.get("id") or ""),
                            }
                            for item in results[:3]
                        ],
                    }
                )
            )
            if not results:
                continue

            if media_type == "artists":
                artist_name = str(results[0].get("name") or normalized_query).strip()
                top_tracks = await self._search_media(artist_name, "tracks")
                logger.warning(
                    json.dumps(
                        {
                            "event": "ma_artist_top_tracks",
                            "request_id": request_id,
                            "home_id": home_id,
                            "player_id": player_id,
                            "intent_name": intent_name,
                            "artist": artist_name,
                            "results_count": len(top_tracks),
                            "result_preview": [
                                {
                                    "name": str(item.get("name") or ""),
                                    "uri": str(item.get("uri") or ""),
                                    "item_id": str(item.get("item_id") or item.get("id") or ""),
                                }
                                for item in top_tracks[:3]
                            ],
                        }
                    )
                )
                if top_tracks:
                    logger.warning(
                        json.dumps(
                            {
                                "event": "ma_artist_enqueue_selected_track",
                                "request_id": request_id,
                                "home_id": home_id,
                                "player_id": player_id,
                                "artist": artist_name,
                                "selected_track": {
                                    "name": str(top_tracks[0].get("name") or ""),
                                    "uri": str(top_tracks[0].get("uri") or ""),
                                    "item_id": str(top_tracks[0].get("item_id") or top_tracks[0].get("id") or ""),
                                },
                            }
                        )
                    )
                    playable = await self._try_enqueue_search_result(
                        top_tracks[0],
                        media_type="tracks",
                        queue_id=effective_queue_id,
                        request_id=request_id,
                        home_id=home_id,
                        player_id=player_id,
                        skip_playback_start=skip_playback_start,
                    )
                    if playable:
                        return playable
                continue

            logger.warning(
                json.dumps(
                    {
                        "event": "ma_direct_enqueue_selected_item",
                        "request_id": request_id,
                        "home_id": home_id,
                        "player_id": player_id,
                        "media_type": media_type,
                        "selected_item": {
                            "name": str(results[0].get("name") or ""),
                            "uri": str(results[0].get("uri") or ""),
                            "item_id": str(results[0].get("item_id") or results[0].get("id") or ""),
                        },
                    }
                )
            )
            playable = await self._try_enqueue_search_result(
                results[0],
                media_type=media_type,
                queue_id=effective_queue_id,
                request_id=request_id,
                home_id=home_id,
                player_id=player_id,
                skip_playback_start=skip_playback_start,
            )
            if playable:
                return playable

        return None

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
        items = await self._post_command_with_fallback(
            self._queue_commands("/items"),
            queue_id=queue_id,
        )
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
            items = await self.get_queue_items(queue_id)
            item = next((i for i in items if i.queue_item_id == queue_item_id), None)
            if item:
                logger.info(json.dumps({
                    "event": "ma_get_queue_item",
                    "request_id": request_id,
                    "home_id": home_id,
                    "player_id": player_id,
                    "queue_id": queue_id,
                    "queue_item_id": queue_item_id,
                    "found": True,
                }))
                return item
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

    async def get_queue_info(self, queue_id: str) -> dict[str, Any]:
        """Return raw queue metadata dict from MA (includes session_id, etc.)."""
        data = await self._post_command_with_fallback(self._queue_commands(), queue_id=queue_id)
        if isinstance(data, dict):
            return data
        return {}

    async def get_current_queue_item(self, queue_id: str) -> Optional[MAQueueItem]:
        """Return the currently-playing queue item, or ``None``."""
        data = await self.get_queue_info(queue_id)
        if data:
            current = data.get("current_item")
            if current:
                return MAQueueItem.model_validate(current)
        return None

    async def get_next_queue_item(self, queue_id: str) -> Optional[MAQueueItem]:
        """Return the next queue item, or ``None`` if queue is exhausted."""
        data = await self._post_command_with_fallback(self._queue_commands(), queue_id=queue_id)
        if data and isinstance(data, dict):
            next_item = data.get("next_item")
            if next_item:
                return MAQueueItem.model_validate(next_item)
        return None

    async def _resolve_default_queue_id(self) -> str | None:
        players = await self.get_players()
        already_tried: set[str] = set()
        for player in players:
            player_id = str(player.get("player_id") or "")
            candidates = [
                ("active_queue", player.get("active_queue")),
                ("active_source", player.get("active_source")),
                ("queue_id", player.get("queue_id")),
                ("player_id", player_id),
            ]
            for candidate_source, candidate in candidates:
                if not candidate:
                    continue
                queue_id = str(candidate).strip()
                if not queue_id:
                    continue
                if queue_id in already_tried:
                    continue
                already_tried.add(queue_id)
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
                    await self._post_command_with_fallback(self._queue_commands(), queue_id=queue_id)
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

    async def _build_ma_stream_url(
        self,
        queue_id: str,
        queue_item_id: str,
        *,
        fmt: str = "mp3",
    ) -> str | None:
        """Construct MA stream server URL — **fast, non-blocking**.

        Returns URL with the best-known session_id.  If none is available
        (no previous MA UI play), uses ``"nosession"``.  When
        ``queue.session_id`` is ``None`` on the MA server (fresh start),
        the stream server skips session validation and any value works.
        """
        from urllib.parse import urlparse

        parsed = urlparse(self._base_url)
        ma_host = parsed.hostname or "127.0.0.1"
        ma_stream_port = 8097

        # ── 1. Check session-ID cache ──────────────────────────────────
        session_id = _get_cached_session_id(queue_id)

        # ── 2. Read players — get player_id + try current_media ────────
        player_id: str | None = None
        try:
            players = await self.get_players()
            for p in players:
                pid = str(p.get("player_id") or "").strip()
                active_queue = str(
                    p.get("active_queue")
                    or p.get("active_source")
                    or p.get("queue_id")
                    or pid
                )
                if active_queue == queue_id:
                    player_id = pid
                    if not session_id:
                        session_id = self._extract_session_id_from_player(p)
                        if session_id:
                            _cache_session_id(queue_id, session_id)
                            logger.info(
                                "_build_ma_stream_url: session_id=%s from current_media",
                                session_id,
                            )
                    break
            if not player_id and players:
                player_id = str(players[0].get("player_id") or "").strip()
        except Exception as exc:
            logger.warning("_build_ma_stream_url: failed to get players: %s", exc)

        if not player_id:
            logger.warning("_build_ma_stream_url: no player_id found queue_id=%s", queue_id)
            return None

        # ── 3. No session? Use "nosession" placeholder ─────────────────
        # When queue.session_id is None (fresh MA start, or restored
        # from cache where session_id is omitted), the stream server
        # skips the session check entirely — any value works.
        if not session_id:
            session_id = "nosession"

        url = f"http://{ma_host}:{ma_stream_port}/single/{session_id}/{queue_id}/{queue_item_id}/{player_id}.{fmt}"
        logger.info(
            "_build_ma_stream_url: url=%s session_id=%s player_id=%s",
            url, session_id, player_id,
        )
        # Pre-warm: fire a background GET to MA's stream server so it resolves
        # streamdetails now.  MA caches them on the queue_item in-memory, so
        # by the time Alexa actually fetches the stream (a few seconds later)
        # the slow part (provider API call) is already done.
        asyncio.create_task(_prewarm_ma_stream_url(url))
        return url

    # ── session-ID helpers ─────────────────────────────────────────────

    @staticmethod
    def _extract_session_id_from_player(player: dict[str, Any]) -> str | None:
        """Extract session_id from Player.current_media.custom_data."""
        cm = player.get("current_media")
        if not isinstance(cm, dict):
            return None
        uri = str(cm.get("uri") or "")
        cd = cm.get("custom_data")
        sid: str | None = None
        if isinstance(cd, dict):
            sid = str(cd.get("session_id") or "").strip() or None
        if not sid and "/single/" in uri:
            parts = uri.split("/single/", 1)
            if len(parts) == 2:
                seg = parts[1].split("/", 1)[0]
                if seg and seg != "nosession":
                    sid = seg
        if sid:
            logger.info(
                "_extract_session_id_from_player: player_id=%s session_id=%s",
                player.get("player_id"), sid,
            )
        return sid

    async def _check_player_session_id(self, queue_id: str) -> str | None:
        """Fast: read session_id from any player whose queue matches."""
        try:
            players = await self.get_players()
            for p in players:
                pid = str(p.get("player_id") or "").strip()
                aq = str(
                    p.get("active_queue")
                    or p.get("active_source")
                    or p.get("queue_id")
                    or pid
                )
                if aq == queue_id or pid == queue_id:
                    sid = self._extract_session_id_from_player(p)
                    if sid:
                        return sid
        except Exception:
            pass
        return None

    async def get_queue_state(self, queue_id: str | None = None) -> dict[str, Any]:
        requested_queue_id = self._sanitize_queue_id(queue_id, source="get_queue_state.request")
        resolved_queue_id = requested_queue_id or await self._resolve_default_queue_id()
        if not resolved_queue_id:
            raise MusicAssistantError(json.dumps({"code": "queue_empty", "message": "No active queue available."}))

        try:
            data = await self._post_command_with_fallback(self._queue_commands(), queue_id=resolved_queue_id)
        except MusicAssistantError as exc:
            if requested_queue_id and self._is_queue_not_found(exc):
                logger.warning(
                    "get_queue_state requested queue_id=%s returned 404; discarding and re-resolving active queue",
                    requested_queue_id,
                )
                resolved_queue_id = await self._resolve_default_queue_id()
                if not resolved_queue_id:
                    raise MusicAssistantError(json.dumps({"code": "queue_empty", "message": "No active queue available."})) from exc
                data = await self._post_command_with_fallback(self._queue_commands(), queue_id=resolved_queue_id)
            else:
                raise
        if not isinstance(data, dict):
            logger.warning(
                "get_queue_state received unexpected response type queue_id=%s type=%s",
                resolved_queue_id,
                type(data).__name__,
            )
            raise MusicAssistantError("MA API error: unexpected queue state response shape")
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

    async def resolve_play_request(
        self,
        queue_id: str | None = None,
        *,
        query: str | None = None,
        intent_name: str = "",
        request_id: str = "",
        home_id: str = "",
        player_id: str = "",
        skip_playback_start: bool = False,
    ) -> dict[str, Any]:
        requested_queue_id = self._sanitize_queue_id(queue_id, source="resolve_play_request.request")
        normalized_query = self._normalize_query(query)
        log_ctx = {
            "event": "ma_resolve_play_request",
            "request_id": request_id,
            "home_id": home_id,
            "player_id": player_id,
            "requested_queue_id": queue_id,
            "intent_name": intent_name,
            "raw_query": query or "",
            "normalized_query": normalized_query,
        }
        logger.warning(json.dumps({**log_ctx, "phase": "start"}))
        try:
            players = await self.get_players()
            logger.warning(
                json.dumps(
                    {
                        "event": "ma_player_inventory",
                        "request_id": request_id,
                        "home_id": home_id,
                        "requested_player_id": player_id,
                        "players": self._player_inventory_snapshot(players),
                    }
                )
            )
        except Exception as exc:
            logger.warning(
                json.dumps(
                    {
                        "event": "ma_player_inventory_failed",
                        "request_id": request_id,
                        "home_id": home_id,
                        "error": str(exc),
                    }
                )
            )

        if normalized_query:
            playable = await self._resolve_query_play_request(
                query=query or "",
                queue_id=requested_queue_id,
                intent_name=intent_name,
                request_id=request_id,
                home_id=home_id,
                player_id=player_id,
                skip_playback_start=skip_playback_start,
            )
            if playable:
                logger.warning(
                    json.dumps(
                        {
                            "event": "ma_query_resolved_to_playable",
                            **log_ctx,
                            "queue_id": playable.get("queue_id"),
                            "queue_item_id": playable.get("queue_item_id"),
                            "item": {
                                "title": str(playable.get("media_details", {}).get("title") or ""),
                                "artist": str(playable.get("media_details", {}).get("artist") or ""),
                                "uri": str(playable.get("media_details", {}).get("uri") or playable.get("uri") or ""),
                            },
                        }
                    )
                )
                return playable

            logger.warning(json.dumps({**log_ctx, "result": "query_no_match"}))
            raise MusicAssistantError(
                json.dumps(
                    {
                        "code": "query_no_match",
                        "message": "No playable results found for the requested query.",
                    }
                )
            )

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

        # Last resort: extract now-playing info from any active player, search
        # the MA library for that content, and enqueue it.
        try:
            fallback_players = await self.get_players()

            def _extract_media_query(fp: dict[str, Any]) -> str:
                """Extract a search query from a player's current media info."""
                # MA serialises current_media as a nested dict with title/artist
                current_media = fp.get("current_media") or fp.get("current_item") or {}
                if isinstance(current_media, dict):
                    title = str(
                        current_media.get("title")
                        or current_media.get("name")
                        or current_media.get("uri")
                        or ""
                    ).strip()
                    artist = str(current_media.get("artist") or "").strip()
                else:
                    title = ""
                    artist = ""
                # Also check top-level player fields as some providers put info there
                if not title:
                    title = str(fp.get("media_title") or fp.get("title") or "").strip()
                if not artist:
                    artist = str(fp.get("media_artist") or fp.get("artist") or "").strip()
                if not title:
                    return ""
                return f"{title} {artist}".strip()

            # Log full diagnostic for every player so we can debug in production
            for fp in fallback_players:
                fp_state = str(fp.get("state") or fp.get("playback_state") or "").lower()
                logger.warning(json.dumps({
                    **log_ctx,
                    "phase": "now_playing_fallback_player_scan",
                    "player_id": str(fp.get("player_id") or ""),
                    "player_name": str(fp.get("name") or ""),
                    "player_state": fp_state,
                    "has_current_media": fp.get("current_media") is not None,
                    "current_media_preview": {
                        k: str(v)[:80] for k, v in (fp.get("current_media") or {}).items()
                    } if isinstance(fp.get("current_media"), dict) else str(fp.get("current_media") or "")[:80],
                    "extracted_query": _extract_media_query(fp),
                }))

            # Two-pass search: first prefer actively-playing players, then any
            # player that has current_media regardless of state.
            active_states = {"playing", "paused", "buffering"}
            ordered_players: list[dict[str, Any]] = []
            deferred_players: list[dict[str, Any]] = []
            for fp in fallback_players:
                fp_state = str(fp.get("state") or fp.get("playback_state") or "").lower()
                if fp_state in active_states:
                    ordered_players.append(fp)
                else:
                    deferred_players.append(fp)
            ordered_players.extend(deferred_players)

            for fp in ordered_players:
                fallback_query = _extract_media_query(fp)
                if not fallback_query:
                    continue
                fp_id = str(fp.get("player_id") or "")
                # Use the best available queue_id: requested > player's active_queue > player_id
                fallback_queue_id = (
                    requested_queue_id
                    or self._sanitize_queue_id(
                        str(fp.get("active_queue") or fp.get("active_source") or fp.get("queue_id") or fp_id or ""),
                        source="now_playing_fallback",
                    )
                )
                logger.warning(json.dumps({
                    **log_ctx,
                    "phase": "now_playing_fallback",
                    "player_id": fp_id,
                    "player_name": str(fp.get("name") or ""),
                    "player_state": str(fp.get("state") or fp.get("playback_state") or ""),
                    "fallback_query": fallback_query,
                    "fallback_queue_id": fallback_queue_id,
                }))
                playable = await self._resolve_query_play_request(
                    query=fallback_query,
                    queue_id=fallback_queue_id,
                    intent_name=intent_name,
                    request_id=request_id,
                    home_id=home_id,
                    player_id=player_id,
                    skip_playback_start=True,
                )
                if playable:
                    logger.warning(json.dumps({
                        **log_ctx,
                        "result": "now_playing_fallback_resolved",
                        "queue_id": playable.get("queue_id"),
                        "queue_item_id": playable.get("queue_item_id"),
                        "source_player_id": fp_id,
                    }))
                    return playable
        except Exception as fallback_exc:
            logger.warning(json.dumps({
                **log_ctx,
                "phase": "now_playing_fallback_failed",
                "error": str(fallback_exc),
            }))

        logger.warning(json.dumps({**log_ctx, "result": "no_playable_item", "reason": "queue_empty"}))
        raise MusicAssistantError(json.dumps({"code": "queue_empty", "message": "No playable queue item available."}))

    async def get_stream_url(self, queue_id: str, item_id: str) -> str | None:
        """Resolve a playable HTTP stream URL from MA for the given queue item.

        Returns ``None`` if no URL can be resolved.
        Provider URIs (apple_music://, spotify://, etc.) are never returned —
        only http:// or https:// URLs that httpx can actually fetch.
        """
        # Check the stream_router cache first (may have been pre-cached).
        # Only return cached value if it is a real HTTP URL.
        from app.edge.stream_router import get_cached_stream_url
        cached = get_cached_stream_url(queue_id, item_id)
        if cached and cached.startswith(("http://", "https://")):
            return cached

        try:
            item = await self.get_queue_item(queue_id, item_id)
            if item and item.streamdetails and item.streamdetails.url:
                url = item.streamdetails.url
                if url.startswith(("http://", "https://")):
                    return url
            # item.uri is a provider URI like apple_music://track/...
            # Do NOT return it — it is not an HTTP URL and cannot be fetched.
            # Fall through to command-based resolution below.

            # Fallback: command-based stream resolution in newer MA builds.
            result = await self._post_command_with_fallback(
                ["player_queues/get_stream_url", "playerqueues/get_stream_url"],
                queue_id=queue_id,
                queue_item_id=item_id,
            )
            if isinstance(result, str) and result.startswith(("http://", "https://")):
                return result
            if isinstance(result, dict):
                url = str(result.get("url") or "").strip()
                if url.startswith(("http://", "https://")):
                    return url
        except MusicAssistantError:
            logger.warning("Stream resolution failed for item %s in queue %s", item_id, queue_id)

        # Fallback: if item_id looks like a URI (synthetic item from search),
        # try to resolve via music/item_by_uri to get stream details.
        uri_to_resolve = item_id if "://" in item_id else None

        # If item_id is not a URI (numeric ID from search), check the URI
        # mapping cache for the original provider URI.
        if not uri_to_resolve:
            from app.edge.stream_router import get_cached_uri_mapping
            uri_to_resolve = get_cached_uri_mapping(queue_id, item_id)
            if uri_to_resolve:
                logger.info(
                    "get_stream_url: found cached URI mapping for %s/%s → %s",
                    queue_id, item_id, uri_to_resolve,
                )

        if uri_to_resolve:
            try:
                media_item = await self._post_command("music/item_by_uri", uri=uri_to_resolve)
                if isinstance(media_item, dict):
                    # Check for stream details — only accept HTTP URLs
                    sd = media_item.get("streamdetails") or {}
                    if isinstance(sd, dict) and sd.get("url"):
                        url = str(sd["url"]).strip()
                        if url.startswith(("http://", "https://")):
                            return url
                    # item.uri from media_item is also a provider URI — skip it
            except MusicAssistantError:
                logger.warning("URI-based stream resolution failed for %s (uri=%s)", item_id, uri_to_resolve)

            # Last resort: try enqueuing with option=add to populate the queue
            # without starting playback, then retry queue item lookup.
            _enqueue_real_queue_id: str | None = None
            try:
                _enqueue_real_queue_id = await self._resolve_default_queue_id()
                if _enqueue_real_queue_id:
                    await self._post_command_with_fallback(
                        ["player_queues/play_media"],
                        queue_id=_enqueue_real_queue_id,
                        media=uri_to_resolve,
                        option="add",
                    )
                    # Item should now be in the queue — retry lookup by the provided item_id.
                    new_item = await self.get_queue_item(_enqueue_real_queue_id, item_id)
                    if new_item:
                        if new_item.streamdetails and new_item.streamdetails.url:
                            url = str(new_item.streamdetails.url).strip()
                            if url.startswith(("http://", "https://")):
                                return url
                        # Item is in the queue but streamdetails not yet populated.
                        # Build the correct MA stream server URL (port 8097, /single/ path).
                        real_item_id = new_item.queue_item_id or item_id
                        enqueue_stream_url = await self._build_ma_stream_url(_enqueue_real_queue_id, real_item_id)
                        if enqueue_stream_url:
                            logger.info(
                                "get_stream_url: enqueue-add resolved stream_url queue_id=%s item_id=%s url=%s",
                                _enqueue_real_queue_id, real_item_id, enqueue_stream_url,
                            )
                            return enqueue_stream_url
                    # Item not found by exact ID — scan all queue items for URI match.
                    all_items = await self.get_queue_items(_enqueue_real_queue_id)
                    for q_item in all_items:
                        if q_item.uri == uri_to_resolve:
                            uri_match_url = await self._build_ma_stream_url(_enqueue_real_queue_id, q_item.queue_item_id)
                            if uri_match_url:
                                logger.info(
                                    "get_stream_url: enqueue-add URI-match stream_url queue_id=%s item_id=%s url=%s",
                                    _enqueue_real_queue_id, q_item.queue_item_id, uri_match_url,
                                )
                                return uri_match_url
            except MusicAssistantError:
                logger.warning("Enqueue-add fallback failed for %s (uri=%s)", item_id, uri_to_resolve)

        # Final fallback: use MA's stream server (port 8097) with the correct
        # /single/{session_id}/{queue_id}/{queue_item_id}/{player_id}.{fmt} URL format.
        # IMPORTANT: use the real MA player queue ID, not the EchoWeave logical queue_id
        # (e.g. "queue-staging"), which MA does not recognise and returns 404.
        _fallback_queue_id = queue_id
        try:
            _resolved_fallback_queue_id = (
                locals().get("_enqueue_real_queue_id")
                or await self._resolve_default_queue_id()
            )
            if _resolved_fallback_queue_id:
                _fallback_queue_id = _resolved_fallback_queue_id
        except Exception:
            pass
        ma_stream_url = await self._build_ma_stream_url(_fallback_queue_id, item_id)
        if not ma_stream_url:
            # Absolute last resort: player_id often equals queue_id in MA.
            from urllib.parse import urlparse as _urlparse
            _parsed = _urlparse(self._base_url)
            _host = _parsed.hostname or "127.0.0.1"
            ma_stream_url = f"http://{_host}:8097/single/echoweave/{_fallback_queue_id}/{item_id}/{_fallback_queue_id}.mp3"
        logger.info(
            "get_stream_url: using MA HTTP stream proxy fallback queue_id=%s fallback_queue_id=%s item_id=%s url=%s",
            queue_id, _fallback_queue_id, item_id, ma_stream_url,
        )
        return ma_stream_url

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

    async def request_alexa_skill_session_bootstrap(
        self,
        *,
        player_id: str,
        request_id: str = "",
        home_id: str = "",
        invocation_names: list[str] | None = None,
    ) -> tuple[bool, str, dict[str, Any]]:
        """Best-effort bootstrap for Alexa skill session from MA control commands.

        This does not guarantee device wake/utterance handling; it attempts known MA
        command namespaces that may route voice/announcement text to Alexa-like players.
        """
        target_player_id = (player_id or "").strip()
        if not target_player_id:
            return False, "missing-player-id", {}

        names = [name.strip() for name in (invocation_names or ["music assistant", "weave bridge"]) if str(name).strip()]
        if not names:
            names = ["music assistant", "weave bridge"]

        attempts: list[tuple[list[str], dict[str, Any], str]] = []
        for invocation_name in names:
            phrase = f"open {invocation_name}"
            attempts.extend(
                [
                    (
                        ["players/cmd/play_announcement"],
                        {"player_id": target_player_id, "message": phrase},
                        f"play_announcement:{invocation_name}",
                    ),
                    (
                        ["players/cmd/tts"],
                        {"player_id": target_player_id, "message": phrase},
                        f"tts:{invocation_name}",
                    ),
                    (
                        ["players/cmd/custom"],
                        {
                            "player_id": target_player_id,
                            "command": "voice_command",
                            "value": phrase,
                        },
                        f"custom_voice_command:{invocation_name}",
                    ),
                ]
            )

        attempt_errors: list[dict[str, str]] = []
        for commands, payload, mode in attempts:
            try:
                logger.info(
                    json.dumps(
                        {
                            "event": "alexa_skill_session_bootstrap_command_attempt",
                            "request_id": request_id,
                            "home_id": home_id,
                            "player_id": target_player_id,
                            "mode": mode,
                            "commands": commands,
                            "payload": payload,
                        },
                        default=str,
                    )
                )
                response = await self._post_command_with_fallback(commands, **payload)
                return True, "bootstrap-command-sent", {
                    "mode": mode,
                    "commands": commands,
                    "payload": payload,
                    "response": response,
                }
            except MusicAssistantError as exc:
                attempt_errors.append({"mode": mode, "error": str(exc)})

        return False, "bootstrap-command-failed", {
            "player_id": target_player_id,
            "attempt_errors": attempt_errors,
        }

    async def handoff_playback_url(
        self,
        *,
        player_id: str,
        playback_url: str,
        preferred_queue_id: str = "",
        request_id: str = "",
        home_id: str = "",
        require_direct_url: bool = False,
    ) -> tuple[bool, str, dict[str, Any]]:
        """Ask MA to play a direct URL on a specific player.

        This is used by ``/ma/push-url`` handoff flow when MA provides a local
        flow URL that must be converted into a public HTTPS URL for Alexa devices.
        """
        target_player_id = (player_id or "").strip()
        target_url = (playback_url or "").strip()
        if not target_player_id:
            return False, "missing-player-id", {}
        if not target_url:
            return False, "missing-playback-url", {}

        handoff_lock = self._get_handoff_player_lock(target_player_id)
        if handoff_lock.locked():
            logger.warning(
                json.dumps(
                    {
                        "event": "ma_handoff_debounced_inflight",
                        "request_id": request_id,
                        "home_id": home_id,
                        "player_id": target_player_id,
                    }
                )
            )
            return False, "handoff-in-flight", {"player_id": target_player_id}

        def _as_bool(value: Any, default: bool = True) -> bool:
            if isinstance(value, bool):
                return value
            if value is None:
                return default
            if isinstance(value, str):
                return value.strip().lower() in {"1", "true", "yes", "on"}
            return bool(value)

        def _extract_error_body(error_text: str) -> str:
            marker = " body="
            idx = error_text.find(marker)
            if idx == -1:
                return error_text
            return error_text[idx + len(marker):].strip()

        def _is_alexa_like_player(player: dict[str, Any]) -> bool:
            fields = [
                str(player.get("provider") or ""),
                str(player.get("source") or ""),
                str(player.get("platform") or ""),
                str(player.get("player_id") or ""),
                str(player.get("name") or ""),
            ]
            blob = " ".join(fields).lower()
            return ("alexa" in blob) or ("echo" in blob)

        def _supports_direct_url_play(player: dict[str, Any]) -> bool:
            caps_blob = " ".join(
                [
                    json.dumps(player.get("supported_features") or "", default=str),
                    json.dumps(player.get("features") or "", default=str),
                    json.dumps(player.get("media_types") or "", default=str),
                    json.dumps(player.get("capabilities") or "", default=str),
                ]
            ).lower()
            indicators = (
                "play_media",
                "media_play",
                "url",
                "http",
                "web",
                "stream",
            )
            return any(indicator in caps_blob for indicator in indicators)

        async with handoff_lock:
            try:
                players = await self.get_players()
                target_player: dict[str, Any] | None = None
                for player in players:
                    candidate_id = str(player.get("player_id") or player.get("id") or "").strip()
                    if candidate_id == target_player_id:
                        target_player = player
                        break

                if target_player is None:
                    return False, "player-not-found", {"player_id": target_player_id}

                logger.info(
                    json.dumps(
                        {
                            "event": "ma_handoff_player_match",
                            "request_id": request_id,
                            "home_id": home_id,
                            "player_id": target_player_id,
                            "player": target_player,
                        },
                        default=str,
                    )
                )

                queue_candidates = [
                    preferred_queue_id,
                    target_player.get("active_queue"),
                    target_player.get("active_source"),
                    target_player.get("queue_id"),
                    target_player.get("player_id"),
                    target_player_id,
                    target_player.get("id"),
                ]
                queue_id = ""
                for candidate in queue_candidates:
                    if not candidate:
                        continue
                    sanitized = self._sanitize_queue_id(str(candidate), source="handoff_playback_url.player")
                    if sanitized:
                        queue_id = sanitized
                        break

                queue_state: dict[str, Any] = {}
                if queue_id:
                    try:
                        queue_state = await self.get_queue_state(queue_id)
                    except MusicAssistantError as exc:
                        logger.debug(
                            json.dumps(
                                {
                                    "event": "ma_handoff_queue_state_unavailable",
                                    "request_id": request_id,
                                    "home_id": home_id,
                                    "player_id": target_player_id,
                                    "queue_id": queue_id,
                                    "error": str(exc),
                                }
                            )
                        )

                provider = str(target_player.get("provider") or target_player.get("source") or "")
                available = _as_bool(target_player.get("available"), True)
                powered = _as_bool(target_player.get("powered"), True)
                active_queue = str(target_player.get("active_queue") or target_player.get("active_source") or "")
                current_item = queue_state.get("current_item", {}) if isinstance(queue_state, dict) else {}
                reported_player_id = str(target_player.get("player_id") or "")
                reported_id = str(target_player.get("id") or "")
                supported_features = target_player.get("supported_features") or target_player.get("features") or []
                media_capabilities = target_player.get("media_types") or target_player.get("capabilities") or []

                logger.info(
                    json.dumps(
                        {
                            "event": "ma_handoff_player_diagnostics",
                            "request_id": request_id,
                            "home_id": home_id,
                            "player_id": target_player_id,
                            "preferred_queue_id": preferred_queue_id,
                            "reported_player_id": reported_player_id,
                            "reported_id": reported_id,
                            "queue_id": queue_id,
                            "provider": provider,
                            "available": available,
                            "powered": powered,
                            "active_queue": active_queue,
                            "current_item": current_item,
                            "supported_features": supported_features,
                            "media_capabilities": media_capabilities,
                        },
                        default=str,
                    )
                )

                attempts: list[tuple[list[str], dict[str, Any], str]] = []
                alexa_like = _is_alexa_like_player(target_player)
                direct_url_supported = _supports_direct_url_play(target_player)
                resume_modes = {"player_resume_play", "queue_resume_play"}
                command_queue_ids: list[str] = []
                for candidate in [queue_id, reported_player_id, target_player_id, active_queue]:
                    normalized = str(candidate or "").strip()
                    if normalized and normalized not in command_queue_ids:
                        command_queue_ids.append(normalized)

                active_queue_id = self._sanitize_queue_id(active_queue, source="handoff_playback_url.active_queue") or ""
                logger.info(
                    json.dumps(
                        {
                            "event": "alexa_start_player_active_queue",
                            "request_id": request_id,
                            "home_id": home_id,
                            "player_id": target_player_id,
                            "active_queue": active_queue,
                            "active_queue_id": active_queue_id,
                            "preferred_queue_id": preferred_queue_id,
                            "candidate_queue_id": queue_id,
                        }
                    )
                )

                validated_active_queue_id = ""
                for active_candidate in [
                    active_queue_id,
                    self._sanitize_queue_id(reported_player_id, source="handoff_playback_url.reported_player_id") or "",
                    self._sanitize_queue_id(str(target_player.get("queue_id") or ""), source="handoff_playback_url.player_queue_id") or "",
                ]:
                    if not active_candidate:
                        continue
                    try:
                        active_state = await self.get_queue_state(active_candidate)
                        if isinstance(active_state, dict) and bool(active_state):
                            validated_active_queue_id = active_candidate
                            break
                    except Exception:
                        continue

                def _queue_media_payloads(selected_queue_id: str) -> list[tuple[dict[str, Any], str]]:
                    # Newer MA builds expect `media` on player_queues/play_media.
                    # Keep a legacy uri/media_type payload last for older variants.
                    return [
                        (
                            {
                                "queue_id": selected_queue_id,
                                "media": target_url,
                                "option": "replace",
                            },
                            "queue_play_media",
                        ),
                        (
                            {
                                "queue_id": selected_queue_id,
                                "media": [target_url],
                                "option": "replace",
                            },
                            "queue_play_media_list",
                        ),
                        (
                            {
                                "queue_id": selected_queue_id,
                                "media": target_url,
                            },
                            "queue_play_media_no_option",
                        ),
                        (
                            {
                                "queue_id": selected_queue_id,
                                "media_type": "url",
                                "uri": target_url,
                            },
                            "queue_play_media_legacy",
                        ),
                    ]

                if alexa_like:
                    logger.info(
                        json.dumps(
                            {
                                "event": "legacy_direct_play_suppressed",
                                "request_id": request_id,
                                "home_id": home_id,
                                "player_id": target_player_id,
                                "suppressed_commands": [
                                    "player_queues/play_media",
                                    "playerqueues/play_media",
                                    "players/play_media",
                                ],
                            }
                        )
                    )

                    validated_alexa_queue_id = ""
                    if queue_id:
                        queue_exists = False
                        queue_lookup_error = ""
                        try:
                            _validated_queue_state = await self.get_queue_state(queue_id)
                            queue_exists = isinstance(_validated_queue_state, dict) and bool(_validated_queue_state)
                        except Exception as exc:
                            queue_exists = False
                            queue_lookup_error = str(exc)

                        queue_matches_active = bool(validated_active_queue_id) and queue_id == validated_active_queue_id
                        if queue_exists and (not validated_active_queue_id or queue_matches_active):
                            validated_alexa_queue_id = queue_id
                            logger.info(
                                json.dumps(
                                    {
                                        "event": "alexa_start_queue_validated",
                                        "request_id": request_id,
                                        "home_id": home_id,
                                        "player_id": target_player_id,
                                        "queue_id": queue_id,
                                        "validated_active_queue_id": validated_active_queue_id,
                                        "queue_matches_active": queue_matches_active,
                                    }
                                )
                            )
                        else:
                            logger.warning(
                                json.dumps(
                                    {
                                        "event": "alexa_start_queue_mismatch",
                                        "request_id": request_id,
                                        "home_id": home_id,
                                        "player_id": target_player_id,
                                        "queue_id": queue_id,
                                        "active_queue_id": validated_active_queue_id or active_queue_id,
                                        "queue_exists": queue_exists,
                                        "queue_matches_active": queue_matches_active,
                                        "queue_lookup_error": queue_lookup_error,
                                    }
                                )
                            )

                    if not validated_alexa_queue_id and validated_active_queue_id:
                        validated_alexa_queue_id = validated_active_queue_id
                        logger.info(
                            json.dumps(
                                {
                                    "event": "alexa_start_queue_validated",
                                    "request_id": request_id,
                                    "home_id": home_id,
                                    "player_id": target_player_id,
                                    "queue_id": validated_alexa_queue_id,
                                    "validated_active_queue_id": validated_active_queue_id,
                                    "queue_matches_active": True,
                                    "reason": "fallback_to_validated_active_queue",
                                }
                            )
                        )

                    if validated_alexa_queue_id:
                        attempts.append(
                            (
                                ["player_queues/play", "playerqueues/play"],
                                {"queue_id": validated_alexa_queue_id},
                                "queue_resume_play",
                            )
                        )
                    else:
                        logger.info(
                            json.dumps(
                                {
                                    "event": "alexa_start_attempt_skipped_invalid_queue",
                                    "request_id": request_id,
                                    "home_id": home_id,
                                    "player_id": target_player_id,
                                    "queue_id": queue_id,
                                    "active_queue_id": validated_active_queue_id or active_queue_id,
                                }
                            )
                        )

                    attempts.append(
                        (
                            ["players/cmd/play"],
                            {"player_id": target_player_id},
                            "player_resume_play",
                        )
                    )
                else:
                    if direct_url_supported:
                        for selected_queue_id in command_queue_ids:
                            for payload, mode in _queue_media_payloads(selected_queue_id):
                                attempts.append(
                                    (
                                        ["player_queues/play_media", "playerqueues/play_media"],
                                        payload,
                                        mode,
                                    )
                                )
                        attempts.append(
                            (
                                ["players/play_media"],
                                {
                                    "player_id": target_player_id,
                                    "media_type": "url",
                                    "uri": target_url,
                                },
                                "player_play_media_alt_namespace",
                            )
                        )

                    # Always include resume path so we avoid hard-failing on providers
                    # where direct URL play is unsupported or intermittently broken.
                    if queue_id:
                        attempts.append(
                            (
                                ["player_queues/play", "playerqueues/play"],
                                {"queue_id": queue_id},
                                "queue_resume_play",
                            )
                        )
                    attempts.append(
                        (
                            ["players/cmd/play"],
                            {"player_id": target_player_id},
                            "player_resume_play",
                        )
                    )

                logger.info(
                    json.dumps(
                        {
                            "event": "ma_handoff_contract_selected",
                            "request_id": request_id,
                            "home_id": home_id,
                            "player_id": target_player_id,
                            "queue_id": queue_id,
                            "provider": provider,
                            "alexa_like": alexa_like,
                            "direct_url_supported": direct_url_supported,
                            "attempt_modes": [mode for _, _, mode in attempts],
                        }
                    )
                )

                for commands, payload, mode in attempts:
                    try:
                        logger.debug(
                            json.dumps(
                                {
                                    "event": "ma_handoff_attempt",
                                    "request_id": request_id,
                                    "home_id": home_id,
                                    "player_id": target_player_id,
                                    "mode": mode,
                                    "commands": commands,
                                    "payload": payload,
                                },
                                default=str,
                            )
                        )
                        response = await self._post_command_with_fallback(commands, **payload)

                        if mode not in resume_modes:
                            # Send an explicit play command to reduce delayed-start edge cases.
                            await self._post_command_with_fallback(["players/cmd/play"], player_id=target_player_id)

                        if require_direct_url and mode in resume_modes:
                            # Optional state sync only; do not treat resume-only as playback success.
                            continue

                        queue_length = 0
                        queue_readback_error = ""
                        if queue_id:
                            try:
                                queue_items = await self.get_queue_items(
                                    queue_id,
                                    request_id=request_id,
                                    home_id=home_id,
                                    player_id=target_player_id,
                                )
                                queue_length = len(queue_items)
                            except Exception as exc:
                                queue_readback_error = str(exc)

                        post_player_state: dict[str, Any] = {}
                        try:
                            post_players = await self.get_players()
                            post_player_state = next(
                                (
                                    p
                                    for p in post_players
                                    if str(p.get("player_id") or p.get("id") or "").strip() == target_player_id
                                ),
                                {},
                            )
                        except Exception:
                            post_player_state = {}

                        current_media = post_player_state.get("current_media")
                        playback_state = str(post_player_state.get("state") or "")
                        active_source = str(
                            post_player_state.get("active_source")
                            or post_player_state.get("active_queue")
                            or ""
                        )

                        logger.info(
                            json.dumps(
                                {
                                    "event": "ma_handoff_post_handoff_state",
                                    "request_id": request_id,
                                    "home_id": home_id,
                                    "player_id": target_player_id,
                                    "mode": mode,
                                    "queue_id": queue_id,
                                    "queue_length": queue_length,
                                    "queue_readback_error": queue_readback_error,
                                    "current_media": current_media,
                                    "playback_state": playback_state,
                                    "active_source": active_source,
                                },
                                default=str,
                            )
                        )

                        if alexa_like and queue_length < 1 and mode not in resume_modes:
                            logger.warning(
                                json.dumps(
                                    {
                                        "event": "ma_handoff_gate_blocked_empty_queue",
                                        "request_id": request_id,
                                        "home_id": home_id,
                                        "player_id": target_player_id,
                                        "mode": mode,
                                        "queue_id": queue_id,
                                        "queue_length": queue_length,
                                        "rollback_player_only": True,
                                    }
                                )
                            )
                            continue

                        logger.info(
                            json.dumps(
                                {
                                    "event": "ma_handoff_final_state_publish_gate",
                                    "request_id": request_id,
                                    "home_id": home_id,
                                    "player_id": target_player_id,
                                    "mode": mode,
                                    "allowed": True,
                                    "queue_length": queue_length,
                                    "playback_state": playback_state,
                                    "active_source": active_source,
                                    "has_current_media": bool(current_media),
                                }
                            )
                        )

                        return True, "playback-command-sent", {
                            "mode": mode,
                            "commands": commands,
                            "payload": payload,
                            "response": response,
                            "player_id": target_player_id,
                            "queue_id": queue_id,
                            "queue_length": queue_length,
                            "playback_state": playback_state,
                            "active_source": active_source,
                            "current_media": current_media,
                        }
                    except MusicAssistantError as exc:
                        error_text = str(exc)
                        logger.warning(
                            json.dumps(
                                {
                                    "event": "ma_handoff_attempt_failed",
                                    "request_id": request_id,
                                    "home_id": home_id,
                                    "player_id": target_player_id,
                                    "mode": mode,
                                    "error": error_text,
                                    "ma_error_body": _extract_error_body(error_text),
                                }
                            )
                        )

                if alexa_like:
                    logger.warning(
                        json.dumps(
                            {
                                "event": "alexa_start_final_result",
                                "request_id": request_id,
                                "home_id": home_id,
                                "player_id": target_player_id,
                                "ok": False,
                                "result": "playback_start_failed",
                                "queue_id": queue_id,
                                "active_queue_id": validated_active_queue_id or active_queue_id,
                            }
                        )
                    )

                fail_message = "direct-url-play-failed" if require_direct_url else "play-media-command-failed"
                return False, fail_message, {
                    "player_id": target_player_id,
                    "queue_id": queue_id,
                    "playback_url": target_url,
                    "rollback_player_only": alexa_like,
                }
            except MusicAssistantAuthError:
                return False, "ma-auth-failed", {"player_id": target_player_id}
            except MusicAssistantUnreachableError:
                return False, "ma-unreachable", {"player_id": target_player_id}
            except MusicAssistantError as exc:
                return False, f"ma-error:{exc}", {"player_id": target_player_id}
