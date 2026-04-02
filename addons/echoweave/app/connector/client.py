from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Any

import httpx

logger = logging.getLogger(__name__)


@dataclass
class ConnectorRuntimeState:
    registered: bool = False
    registration_message: str = "not-started"
    last_heartbeat_status: str = "never"
    last_heartbeat_at: str = ""

    def snapshot(self) -> dict[str, str | bool]:
        return {
            "registered": self.registered,
            "registration_message": self.registration_message,
            "last_heartbeat_status": self.last_heartbeat_status,
            "last_heartbeat_at": self.last_heartbeat_at,
        }


class ConnectorClient:
    """Connector-side HTTP client for cloud registration and heartbeats."""

    def __init__(
        self,
        *,
        backend_url: str,
        connector_id: str,
        connector_secret: str,
        tenant_id: str,
        home_id: str,
    ) -> None:
        self.backend_url = backend_url.rstrip("/")
        self.connector_id = connector_id
        self.connector_secret = connector_secret
        self.tenant_id = tenant_id
        self.home_id = home_id
        self.state = ConnectorRuntimeState()

    async def register(self, capabilities: dict[str, Any] | None = None) -> bool:
        payload = {
            "connector_id": self.connector_id,
            "tenant_id": self.tenant_id,
            "home_id": self.home_id,
            "connector_secret": self.connector_secret,
            "capabilities": capabilities or {},
        }
        url = f"{self.backend_url}/v1/connectors/register"
        try:
            # Get bootstrap secret from config if available
            config_svc = getattr(self, '_config_service', None)
            bootstrap_secret = ""
            if config_svc:
                try:
                    bootstrap_secret = config_svc.settings.connector_bootstrap_secret or ""
                except Exception:
                    pass
            
            headers = {"x-connector-bootstrap-secret": bootstrap_secret} if bootstrap_secret else {}
            
            async with httpx.AsyncClient(timeout=10) as client:
                if headers:
                    resp = await client.post(url, json=payload, headers=headers)
                else:
                    resp = await client.post(url, json=payload)
            
            if resp.status_code != 200:
                self.state.registered = False
                self.state.registration_message = f"register-failed:{resp.status_code}"
                logger.warning(
                    "Connector registration failed: status=%s bootstrap_set=%s body=%s",
                    resp.status_code,
                    bool(bootstrap_secret),
                    resp.text,
                )
                return False
            self.state.registered = True
            self.state.registration_message = "registered"
            logger.info(
                "Connector registered: connector_id=%s tenant_id=%s home_id=%s bootstrap_set=%s",
                self.connector_id,
                self.tenant_id,
                self.home_id,
                bool(bootstrap_secret),
            )
            return True
        except Exception as exc:
            self.state.registered = False
            self.state.registration_message = f"register-exception:{type(exc).__name__}"
            logger.exception("Connector registration error")
            return False

    async def heartbeat(self, status: str = "online") -> bool:
        url = f"{self.backend_url}/v1/connectors/{self.connector_id}/heartbeat"
        payload = {
            "connector_secret": self.connector_secret,
            "status": status,
        }
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.post(url, json=payload)
            if resp.status_code != 200:
                self.state.last_heartbeat_status = f"failed:{resp.status_code}"
                self.state.last_heartbeat_at = datetime.utcnow().isoformat() + "Z"
                logger.warning(
                    "Connector heartbeat failed: status=%s body=%s",
                    resp.status_code,
                    resp.text,
                )
                return False
            data = resp.json()
            self.state.last_heartbeat_status = data.get("status", status)
            self.state.last_heartbeat_at = data.get("last_seen", datetime.utcnow().isoformat() + "Z")
            return True
        except Exception as exc:
            self.state.last_heartbeat_status = f"error:{type(exc).__name__}"
            self.state.last_heartbeat_at = datetime.utcnow().isoformat() + "Z"
            logger.exception("Connector heartbeat error")
            return False

    async def poll_next_command(self) -> dict[str, Any] | None:
        url = f"{self.backend_url}/v1/connectors/{self.connector_id}/commands/next"
        payload = {"connector_secret": self.connector_secret}
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.post(url, json=payload)
            if resp.status_code == 401:
                logger.warning("Connector command poll unauthorized: connector_id=%s", self.connector_id)
                return None
            if resp.status_code != 200:
                logger.warning("Connector command poll failed: status=%s body=%s", resp.status_code, resp.text)
                return None
            data = resp.json()
            if not data:
                return None
            return data
        except Exception:
            logger.exception("Connector command poll error")
            return None

    async def ack_command(
        self,
        *,
        command_id: str,
        success: bool,
        message: str,
        result: dict[str, Any] | None = None,
    ) -> bool:
        url = f"{self.backend_url}/v1/connectors/{self.connector_id}/commands/{command_id}/ack"
        payload = {
            "connector_secret": self.connector_secret,
            "success": success,
            "message": message,
            "result": result or {},
        }
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.post(url, json=payload)
            if resp.status_code != 200:
                logger.warning("Connector command ack failed: command_id=%s status=%s body=%s", command_id, resp.status_code, resp.text)
                return False
            return True
        except Exception:
            logger.exception("Connector command ack error: command_id=%s", command_id)
            return False