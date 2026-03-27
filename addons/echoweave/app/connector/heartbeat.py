from __future__ import annotations

import asyncio
import logging
from typing import Awaitable, Callable

from app.connector.client import ConnectorClient

logger = logging.getLogger(__name__)


class HeartbeatRunner:
    def __init__(
        self,
        client: ConnectorClient,
        interval_seconds: int = 30,
        command_handler: Callable[[dict], Awaitable[tuple[bool, str, dict]]] | None = None,
    ) -> None:
        self._client = client
        self._interval_seconds = interval_seconds
        self._command_handler = command_handler
        self._task: asyncio.Task | None = None
        self._stop = asyncio.Event()

    async def start(self) -> None:
        if self._task and not self._task.done():
            return
        self._stop.clear()
        self._task = asyncio.create_task(self._run(), name="connector-heartbeat")

    async def _run(self) -> None:
        while not self._stop.is_set():
            await self._client.heartbeat(status="online")
            await self._poll_and_process_command()
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=self._interval_seconds)
            except asyncio.TimeoutError:
                continue

    async def _poll_and_process_command(self) -> None:
        if self._command_handler is None:
            return
        command = await self._client.poll_next_command()
        if not command:
            return

        command_id = str(command.get("command_id", ""))
        try:
            success, message, result = await self._command_handler(command)
            await self._client.ack_command(
                command_id=command_id,
                success=success,
                message=message,
                result=result,
            )
            logger.info(
                "connector_command_ack_sent command_id=%s success=%s message=%s",
                command_id,
                success,
                message,
            )
        except Exception:
            logger.exception("connector_command_execute_error command_id=%s", command_id)
            await self._client.ack_command(
                command_id=command_id,
                success=False,
                message="connector-exception",
                result={},
            )

    async def stop(self) -> None:
        self._stop.set()
        if self._task:
            await self._task
            self._task = None

    async def close(self) -> None:
        await self.stop()

    def snapshot(self) -> dict[str, str]:
        return {
            "registered": str(self._client.state.registered).lower(),
            "registration_message": self._client.state.registration_message,
            "last_heartbeat_status": self._client.state.last_heartbeat_status,
            "last_heartbeat_at": self._client.state.last_heartbeat_at,
        }
