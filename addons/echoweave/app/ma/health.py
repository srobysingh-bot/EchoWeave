"""Music Assistant connectivity and stream URL health checks."""

from __future__ import annotations

import logging
from typing import Any

import httpx

from app.ma.client import MusicAssistantClient

logger = logging.getLogger(__name__)


class MAHealthChecker:
    """Run health probes against the Music Assistant server."""

    def __init__(self, ma_client: MusicAssistantClient) -> None:
        self._ma = ma_client

    async def check_reachable(self) -> dict[str, Any]:
        """Probe whether the MA server is reachable."""
        reachable = await self._ma.ping()
        return {
            "key": "ma_reachable",
            "status": "ok" if reachable else "fail",
            "message": "Music Assistant is reachable." if reachable else "Cannot reach Music Assistant server.",
        }

    async def check_auth(self) -> dict[str, Any]:
        """Validate that our token is accepted by MA."""
        try:
            valid = await self._ma.validate_token()
            return {
                "key": "ma_auth_valid",
                "status": "ok" if valid else "fail",
                "message": "Token accepted." if valid else "Token rejected by Music Assistant.",
            }
        except Exception as exc:
            return {
                "key": "ma_auth_valid",
                "status": "fail",
                "message": f"Auth check error: {exc}",
            }

    @staticmethod
    async def check_stream_url(stream_base_url: str) -> dict[str, Any]:
        """Verify that the stream base URL is reachable (HEAD request)."""
        if not stream_base_url:
            return {
                "key": "stream_url_valid",
                "status": "warn",
                "message": "Stream base URL not configured.",
            }
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.head(stream_base_url)
            ok = resp.status_code < 500
            return {
                "key": "stream_url_valid",
                "status": "ok" if ok else "warn",
                "message": f"Stream URL responded with {resp.status_code}.",
            }
        except Exception as exc:
            return {
                "key": "stream_url_valid",
                "status": "fail",
                "message": f"Stream URL unreachable: {exc}",
            }

    async def run_all(self, stream_base_url: str = "") -> list[dict[str, Any]]:
        """Run all MA-related health checks and return results."""
        results = [
            await self.check_reachable(),
            await self.check_auth(),
            await self.check_stream_url(stream_base_url),
        ]
        return results
