from __future__ import annotations

import asyncio
import json
import logging
import random
import time
from collections.abc import Awaitable, Callable
from typing import Any
from urllib.parse import urlencode

import websockets
from websockets.exceptions import ConnectionClosed

from app.edge.models import (
    AddonStatePayload,
    ConnectorAuthEnvelope,
    ConnectorHelloEnvelope,
    EdgeCommandEnvelope,
    EdgeRequestEnvelope,
    EdgeResponseEnvelope,
    ErrorPayload,
)

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
        source_queue_id: str = "",
        reconnect_base_seconds: float = 1.0,
        reconnect_max_seconds: float = 15.0,
    ) -> None:
        self._worker_base_url = worker_base_url.rstrip("/")
        self._connector_id = connector_id
        self._connector_secret = connector_secret
        self._tenant_id = tenant_id
        self._home_id = home_id
        self._source_queue_id = source_queue_id
        self._command_handler = command_handler
        self._reconnect_base_seconds = reconnect_base_seconds
        self._reconnect_max_seconds = reconnect_max_seconds

        self._task: asyncio.Task | None = None
        self._stop_event = asyncio.Event()
        self._socket: Any | None = None
        self._send_lock = asyncio.Lock()
        self._pending: dict[str, asyncio.Future[dict[str, Any]]] = {}
        self.is_connected: bool = False
        self.last_connected_at: float | None = None

        self._capabilities = {
            "commands": [
                "prepare_play",
                "resolve_stream",
                "get_current_item",
                "get_next_item",
                "get_state",
                "pause",
                "resume",
                "stop",
                "next",
                "previous",
            ],
            "stream_route": "/edge/stream/{queue_id}/{queue_item_id}",
        }

    @property
    def ws_url(self) -> str:
        base = self._worker_base_url.replace("https://", "wss://").replace("http://", "ws://")
        query = urlencode(
            {
                "connector_id": self._connector_id,
                "connector_secret": self._connector_secret,
                "tenant_id": self._tenant_id,
                "home_id": self._home_id,
            }
        )
        return f"{base}/v1/connectors/ws?{query}"

    @property
    def redacted_ws_url(self) -> str:
        base = self._worker_base_url.replace("https://", "wss://").replace("http://", "ws://")
        return (
            f"{base}/v1/connectors/ws"
            f"?connector_id={self._connector_id}"
            "&connector_secret=****"
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
        await self._fail_pending("ws-client-stopped")
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
        self._socket = None

    def snapshot(self) -> dict[str, Any]:
        return {
            "connected": self.is_connected,
            "last_connected_at": self.last_connected_at,
            "pending_requests": len(self._pending),
            "worker_endpoint": self.redacted_ws_url,
        }

    async def send_request(self, action: str, payload: dict[str, Any], *, timeout_seconds: float = 8.0) -> dict[str, Any]:
        if not self.is_connected or self._socket is None:
            raise RuntimeError("connector-offline")

        request_id = f"req-{uuid4_hex()}"
        envelope = EdgeRequestEnvelope(
            request_id=request_id,
            action=action,
            payload=payload,
        )
        future: asyncio.Future[dict[str, Any]] = asyncio.get_running_loop().create_future()
        self._pending[request_id] = future
        try:
            await self._send_json(envelope.model_dump())
            return await asyncio.wait_for(future, timeout=timeout_seconds)
        except Exception:
            self._pending.pop(request_id, None)
            raise

    async def _run_loop(self) -> None:
        attempt = 0
        while not self._stop_event.is_set():
            try:
                logger.info("Edge connector connecting to worker ws endpoint: %s", self.redacted_ws_url)
                async with websockets.connect(self.ws_url, ping_interval=20, ping_timeout=20) as ws:
                    attempt = 0
                    self.is_connected = True
                    self.last_connected_at = time.time()
                    self._socket = ws
                    logger.info("Edge connector ws connected.")
                    await self._send_connector_hello()
                    async for message in ws:
                        await self._handle_message(message)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.warning("Edge connector ws connection dropped: %s", self._redact_error(exc))
                self.is_connected = False
                self._socket = None
                await self._fail_pending("connector-disconnected")

            if self._stop_event.is_set():
                break
            attempt += 1
            await asyncio.sleep(self._compute_backoff(attempt))
        self.is_connected = False
        self._socket = None

    def _compute_backoff(self, attempt: int) -> float:
        base = min(self._reconnect_base_seconds * (2 ** max(0, attempt - 1)), self._reconnect_max_seconds)
        jitter = random.uniform(0.0, min(1.0, base / 3.0))
        return base + jitter

    async def _send_connector_hello(self) -> None:
        hello_payload = AddonStatePayload(
            online=True,
            connector_id=self._connector_id,
            tenant_id=self._tenant_id,
            home_id=self._home_id,
            capabilities=self._capabilities,
            queue_id=self._source_queue_id,
        )
        hello = ConnectorHelloEnvelope(payload=hello_payload)
        auth = ConnectorAuthEnvelope(payload={"auth": "query", "connector_id": self._connector_id})
        await self._send_json(hello.model_dump())
        await self._send_json(auth.model_dump())

    async def _send_json(self, payload: dict[str, Any]) -> None:
        if self._socket is None:
            raise RuntimeError("connector-offline")
        encoded = json.dumps(payload, separators=(",", ":"))
        async with self._send_lock:
            await self._socket.send(encoded)

    async def _fail_pending(self, reason: str) -> None:
        for request_id, future in list(self._pending.items()):
            if not future.done():
                future.set_exception(RuntimeError(reason))
            self._pending.pop(request_id, None)

    async def _handle_message(self, raw_message: str) -> None:
        try:
            payload = json.loads(raw_message)
        except Exception:
            logger.warning("Edge connector received invalid command envelope.")
            return

        msg_type = str(payload.get("type") or "")
        if msg_type == "response":
            await self._handle_response(payload)
            return

        if msg_type != "command":
            logger.debug("Ignoring unsupported edge ws message type=%s", msg_type)
            return

        envelope = EdgeCommandEnvelope.model_validate(payload)
        logger.info(
            "edge_ws_command_received request_id=%s command_type=%s payload_queue_id=%s",
            envelope.request_id,
            envelope.command_type,
            str(envelope.payload.get("queue_id") or ""),
        )

        try:
            result = await self._command_handler(envelope.command_type, envelope.payload)
            response = EdgeResponseEnvelope(
                request_id=envelope.request_id,
                ok=True,
                payload=result,
            )
            logger.info(
                "edge_ws_command_response request_id=%s ok=true queue_id=%s queue_item_id=%s origin_stream_path=%s",
                envelope.request_id,
                str(result.get("queue_id") or ""),
                str(result.get("queue_item_id") or ""),
                str(result.get("origin_stream_path") or ""),
            )
        except Exception as exc:
            logger.exception("Edge command failed: command=%s", envelope.command_type)
            response = EdgeResponseEnvelope(
                request_id=envelope.request_id,
                ok=False,
                error=ErrorPayload(
                    code="edge-command-failed",
                    message=str(exc),
                    details={"command_type": envelope.command_type},
                ),
            )
            logger.error(
                "edge_ws_command_response request_id=%s ok=false error_code=edge-command-failed error_message=%s",
                envelope.request_id,
                str(exc),
            )

        await self._send_json(response.model_dump())

    async def _handle_response(self, payload: dict[str, Any]) -> None:
        envelope = EdgeResponseEnvelope.model_validate(payload)
        pending = self._pending.pop(envelope.request_id, None)
        if pending is None:
            return
        if envelope.ok:
            pending.set_result(envelope.payload)
            return
        message = envelope.error.message if envelope.error else "edge-response-error"
        pending.set_exception(RuntimeError(message))

    def _redact_error(self, exc: Exception) -> str:
        return str(exc).replace(self._connector_secret, "****")


def uuid4_hex() -> str:
    import uuid

    return uuid.uuid4().hex
