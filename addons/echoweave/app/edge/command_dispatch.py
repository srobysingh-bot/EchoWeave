from __future__ import annotations

import logging
from typing import Any

from app.ma.client import MusicAssistantClient

logger = logging.getLogger(__name__)


async def execute_edge_command(command_type: str, payload: dict[str, Any], ma_client: MusicAssistantClient) -> dict[str, Any]:
    command = (command_type or "").strip().lower()

    if command == "prepare_play":
        queue_id = str(payload.get("queue_id") or "")
        resolved = await ma_client.resolve_play_request(queue_id=queue_id or None)
        return resolved

    if command == "get_current_item":
        queue_id = str(payload.get("queue_id") or "")
        item = await ma_client.get_current_playable_item(queue_id)
        return item or {}

    if command == "get_next_item":
        queue_id = str(payload.get("queue_id") or "")
        item = await ma_client.get_next_playable_item(queue_id)
        return item or {}

    if command == "get_state":
        queue_id = str(payload.get("queue_id") or "")
        return await ma_client.get_queue_state(queue_id)

    if command in {"pause", "resume", "stop", "next", "previous"}:
        # Alexa is the playback device in edge mode; these are metadata-level actions for now.
        logger.info("Edge command received for playback control command=%s payload=%s", command, {"queue_id": payload.get("queue_id")})
        return {"status": "accepted", "command": command}

    raise ValueError(f"Unsupported edge command: {command_type}")
