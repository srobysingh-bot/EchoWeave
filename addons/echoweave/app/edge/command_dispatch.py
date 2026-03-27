from __future__ import annotations

import logging
from typing import Any

from app.edge.models import PreparePlayPayload
from app.ma.client import MusicAssistantClient

logger = logging.getLogger(__name__)


async def execute_edge_command(
    command_type: str,
    payload: dict[str, Any],
    ma_client: MusicAssistantClient,
    *,
    default_queue_id: str = "",
) -> dict[str, Any]:
    command = (command_type or "").strip().lower()
    queue_id = str(payload.get("queue_id") or default_queue_id or "")

    if command == "prepare_play":
        prepare = PreparePlayPayload.model_validate(payload)
        requested_queue_id = (prepare.queue_id or queue_id).strip() or None
        resolved = await ma_client.resolve_play_request(queue_id=requested_queue_id)
        resolved["intent_name"] = prepare.intent_name
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
