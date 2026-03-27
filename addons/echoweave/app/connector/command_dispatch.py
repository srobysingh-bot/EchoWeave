from __future__ import annotations

import logging
from typing import Any

from app.ma.client import MusicAssistantClient

logger = logging.getLogger(__name__)


async def execute_connector_command(command: dict[str, Any], ma_client: MusicAssistantClient) -> tuple[bool, str, dict[str, Any]]:
    """Execute a cloud-issued connector command against local MA.

    Returns a tuple: ``(success, message, result_payload)``.
    """
    command_id = str(command.get("command_id", ""))
    command_type = str(command.get("command_type", "")).lower()
    payload = command.get("payload", {}) or {}

    logger.info(
        "connector_command_execute command_id=%s command_type=%s payload_summary=%s",
        command_id,
        command_type,
        {
            "action": payload.get("action", ""),
            "intent_name": payload.get("intent_name", ""),
            "request_type": payload.get("request_type", ""),
        },
    )

    if command_type == "play":
        queue_id = payload.get("queue_id")
        ok, message = await ma_client.execute_play_command(queue_id=queue_id)
        result = {"queue_id": queue_id or "", "message": message}
        return ok, message, result

    return False, f"unsupported-command:{command_type}", {"command_type": command_type}
