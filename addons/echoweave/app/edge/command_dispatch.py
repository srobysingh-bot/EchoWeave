from __future__ import annotations

import json
import logging
import re
import time
from typing import Any

import httpx

from app.core.exceptions import MusicAssistantError
from app.edge.models import PreparePlayPayload
from app.edge.stream_router import cache_stream_url
from app.ma.client import MusicAssistantClient

logger = logging.getLogger(__name__)


def _normalize_query(query: str) -> str:
    normalized = re.sub(r"\s+", " ", (query or "").strip().lower())
    normalized = re.sub(r"^(songs?|music)\s+by\s+", "", normalized)
    return normalized.strip()


async def execute_edge_command(
    command_type: str,
    payload: dict[str, Any],
    ma_client: MusicAssistantClient,
    *,
    default_queue_id: str = "",
) -> dict[str, Any]:
    command = (command_type or "").strip().lower()
    queue_id = str(payload.get("queue_id") or default_queue_id or "")

    logger.info(
        "edge_command_received command_type=%s payload_queue_id=%s resolved_queue_id=%s",
        command,
        str(payload.get("queue_id") or ""),
        queue_id,
    )

    if command == "prepare_play":
        prepare = PreparePlayPayload.model_validate(payload)
        requested_queue_id = (prepare.queue_id or queue_id).strip() or None
        raw_query = (prepare.query or "").strip()
        normalized_query = _normalize_query(raw_query)
        logger.warning(
            "prepare_play_start requested_queue_id=%s default_queue_id=%s intent_name=%s raw_query=%s normalized_query=%s",
            requested_queue_id,
            default_queue_id,
            prepare.intent_name,
            raw_query,
            normalized_query,
        )
        try:
            resolved = await ma_client.resolve_play_request(
                queue_id=requested_queue_id,
                query=raw_query or None,
                intent_name=prepare.intent_name,
            )
            logger.info(
                "prepare_play_primary_resolve_ok queue_id=%s queue_item_id=%s origin_stream_path=%s",
                resolved.get("queue_id"),
                resolved.get("queue_item_id"),
                resolved.get("origin_stream_path"),
            )
        except MusicAssistantError as exc:
            logger.warning(
                "prepare_play_primary_resolve_error exception_type=%s exception_message=%s queue_id=%s",
                type(exc).__name__,
                str(exc),
                requested_queue_id,
            )
            # If a configured queue binding is stale, retry with MA auto-discovery.
            if not requested_queue_id:
                raise
            logger.warning(
                "prepare_play failed for queue_id=%s; retrying with auto-discovered active queue",
                requested_queue_id,
            )
            logger.info("prepare_play_fallback_entered requested_queue_id=%s", requested_queue_id)
            try:
                resolved = await ma_client.resolve_play_request(
                    queue_id=None,
                    query=raw_query or None,
                    intent_name=prepare.intent_name,
                )
                logger.info(
                    "prepare_play_fallback_resolve_ok queue_id=%s queue_item_id=%s origin_stream_path=%s",
                    resolved.get("queue_id"),
                    resolved.get("queue_item_id"),
                    resolved.get("origin_stream_path"),
                )
            except Exception as fallback_exc:
                logger.error(
                    "prepare_play_fallback_resolve_error exception_type=%s exception_message=%s",
                    type(fallback_exc).__name__,
                    str(fallback_exc),
                )
                raise
        resolved["intent_name"] = prepare.intent_name
        logger.info(
            "prepare_play_result queue_id=%s queue_item_id=%s origin_stream_path=%s",
            resolved.get("queue_id"),
            resolved.get("queue_item_id"),
            resolved.get("origin_stream_path"),
        )
        
        # Cache the stream URL to avoid re-fetching during stream request
        queue_id_val = resolved.get("queue_id")
        queue_item_id_val = resolved.get("queue_item_id")
        if queue_id_val and queue_item_id_val:
            # Build stream context to get the actual source URL without blocking stream endpoint
            try:
                stream_ctx = await ma_client.build_stream_context(
                    queue_id=queue_id_val,
                    queue_item_id=queue_item_id_val,
                )
                source_url = stream_ctx.get("source_url")
                if source_url:
                    cache_stream_url(queue_id_val, queue_item_id_val, source_url)
                    logger.debug(f"Cached stream URL for {queue_id_val}/{queue_item_id_val}")
            except Exception as cache_exc:
                logger.warning(f"Failed to cache stream URL: {cache_exc}")
                # Don't fail prepare_play if caching fails
        
        return resolved

    if command == "resolve_stream":
        queue_id_val = str(payload.get("queue_id") or "").strip()
        queue_item_id_val = str(payload.get("queue_item_id") or "").strip()
        request_id = str(payload.get("request_id") or payload.get("token_id") or "")
        token_id = str(payload.get("token_id") or "")
        playback_session_id = str(payload.get("playback_session_id") or "")

        logger.info(
            json.dumps(
                {
                    "event": "edge_stream_request_start",
                    "request_id": request_id,
                    "token_id": token_id,
                    "playback_session_id": playback_session_id,
                    "queue_id": queue_id_val,
                    "queue_item_id": queue_item_id_val,
                }
            )
        )

        stream_ctx = await ma_client.build_stream_context(queue_id=queue_id_val, queue_item_id=queue_item_id_val)
        source_url = str(stream_ctx.get("source_url") or "")
        if not source_url:
            raise MusicAssistantError("stream_source_unavailable")

        logger.info(
            json.dumps(
                {
                    "event": "edge_stream_lookup_done",
                    "request_id": request_id,
                    "token_id": token_id,
                    "playback_session_id": playback_session_id,
                    "queue_id": queue_id_val,
                    "queue_item_id": queue_item_id_val,
                    "origin_stream_path": stream_ctx.get("origin_stream_path", ""),
                }
            )
        )

        probe_status = 0
        first_byte_ms = 0.0
        probe_headers: dict[str, str] = {}
        probe_start = time.perf_counter()
        try:
            timeout = httpx.Timeout(10.0, connect=5.0)
            async with httpx.AsyncClient(timeout=timeout, follow_redirects=False) as client:
                probe_resp = await client.get(source_url, headers={"Range": "bytes=0-0"})
                first_byte_ms = round((time.perf_counter() - probe_start) * 1000, 1)
                probe_status = probe_resp.status_code
                probe_headers = {
                    "content_type": probe_resp.headers.get("content-type", ""),
                    "accept_ranges": probe_resp.headers.get("accept-ranges", ""),
                    "content_range": probe_resp.headers.get("content-range", ""),
                    "content_length": probe_resp.headers.get("content-length", ""),
                }
                logger.info(
                    json.dumps(
                        {
                            "event": "edge_stream_upstream_first_byte",
                            "request_id": request_id,
                            "token_id": token_id,
                            "playback_session_id": playback_session_id,
                            "queue_id": queue_id_val,
                            "queue_item_id": queue_item_id_val,
                            "first_byte_ms": first_byte_ms,
                            "upstream_status": probe_status,
                        }
                    )
                )
        except Exception as exc:
            first_byte_ms = round((time.perf_counter() - probe_start) * 1000, 1)
            logger.warning(
                json.dumps(
                    {
                        "event": "edge_stream_upstream_first_byte",
                        "request_id": request_id,
                        "token_id": token_id,
                        "playback_session_id": playback_session_id,
                        "queue_id": queue_id_val,
                        "queue_item_id": queue_item_id_val,
                        "first_byte_ms": first_byte_ms,
                        "upstream_status": 0,
                        "error": str(exc),
                    }
                )
            )

        logger.info(
            json.dumps(
                {
                    "event": "edge_stream_response",
                    "request_id": request_id,
                    "token_id": token_id,
                    "playback_session_id": playback_session_id,
                    "queue_id": queue_id_val,
                    "queue_item_id": queue_item_id_val,
                    "status": probe_status,
                    "first_byte_ms": first_byte_ms,
                    "content_type": probe_headers.get("content_type", ""),
                    "accept_ranges": probe_headers.get("accept_ranges", ""),
                    "content_length": probe_headers.get("content_length", ""),
                    "content_range": probe_headers.get("content_range", ""),
                    "source_url": source_url,
                }
            )
        )

        return {
            "queue_id": queue_id_val,
            "queue_item_id": queue_item_id_val,
            "origin_stream_path": stream_ctx.get("origin_stream_path", ""),
            "source_url": source_url,
            "content_type": stream_ctx.get("content_type", "audio/mpeg"),
        }

    if command == "get_current_item":
        item = await ma_client.get_current_playable_item(queue_id or None)
        return item or {}

    if command == "get_next_item":
        item = await ma_client.get_next_playable_item(queue_id or None)
        return item or {}

    if command == "get_state":
        return await ma_client.get_queue_state(queue_id or None)

    if command in {"pause", "resume", "stop", "next", "previous"}:
        # Alexa is the playback device in edge mode; these are metadata-level actions for now.
        logger.info(
            "Edge command received for playback control command=%s queue_id=%s",
            command,
            queue_id,
        )
        state = await ma_client.get_queue_state(queue_id or None)
        return {
            "status": "accepted",
            "command": command,
            "queue_state": state,
        }

    raise ValueError(f"Unsupported edge command: {command_type}")
