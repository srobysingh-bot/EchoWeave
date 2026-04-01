from __future__ import annotations

import logging
import re
from typing import Any

from app.core.exceptions import MusicAssistantError
from app.edge.models import PreparePlayPayload
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
        logger.info(
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
        return resolved

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
