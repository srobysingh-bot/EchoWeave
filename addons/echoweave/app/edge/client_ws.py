from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import Awaitable, Callable

import websockets

from app.edge.models import EdgeCommandEnvelope, EdgeResponseEnvelope

logger = logging.getLogger(__name__)

CommandHandler = Callable[[str, dict], Awaitable[dict]]


class EdgeConnectorWSClient:
    """Persistent outbound connector WebSocket client for edge mode."""

    def __init__(
        self,
        *,
        worker_base_url: str,
        connector_id: str,
        connector_secret: str,
        tenant_id: str,
        home_id: str,
        command_handler: CommandHandler,
        reconnect_seconds: int = 3,
    ) -> None:
        self._worker_base_url = worker_base_url.rstrip("/")
        self._connector_id = connector_id
        self._connector_secret = connector_secret
        self._tenant_id = tenant_id
        self._home_id = home_id
        self._command_handler = command_handler
        self._reconnect_seconds = reconnect_seconds

        self._task: asyncio.Task | None = None
        self._stop_event = asyncio.Event()
        self.is_connected: bool = False

    @property
    def ws_url(self) -> str:
        base = self._worker_base_url.replace("https://", "wss://").replace("http://", "ws://")
        return (
            f"{base}/v1/connectors/ws"
            f"?connector_id={self._connector_id}"
            f"&connector_secret={self._connector_secret}"
            f"&tenant_id={self._tenant_id}"
            f"&home_id={self._home_id}"
        )

    async def start(self) -> None:
        if self._task and not self._task.done():
            return
        self._stop_event.clear()
        self._task = asyncio.create_task(self._run_loop(), name="edge-connector-ws")

    async def close(self) -> None:
        self._stop_event.set()
        self.is_connected = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None

    async def _run_loop(self) -> None:
        while not self._stop_event.is_set():
            try:
                logger.info("Edge connector connecting to worker ws endpoint.")
                async with websockets.connect(self.ws_url, ping_interval=20, ping_timeout=20) as ws:
                    self.is_connected = True
                    logger.info("Edge connector ws connected.")
                    async for message in ws:
                        await self._handle_message(ws, message)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.warning("Edge connector ws connection dropped: %s", exc)
                self.is_connected = False

            if self._stop_event.is_set():
                break
            await asyncio.sleep(self._reconnect_seconds)
        self.is_connected = False

    async def _handle_message(self, ws: websockets.WebSocketClientProtocol, raw_message: str) -> None:
        try:
            payload = json.loads(raw_message)
            envelope = EdgeCommandEnvelope.model_validate(payload)
        except Exception:
            logger.warning("Edge connector received invalid command envelope.")
            return

        try:
            result = await self._command_handler(envelope.command_type, envelope.payload)
            response = EdgeResponseEnvelope(
                request_id=envelope.request_id,
                ok=True,
                payload=result,
            )
        except Exception as exc:
            logger.exception("Edge command failed: command=%s", envelope.command_type)
            response = EdgeResponseEnvelope(
                request_id=envelope.request_id,
                ok=False,
                error=str(exc),
            )

        await ws.send(response.model_dump_json())
