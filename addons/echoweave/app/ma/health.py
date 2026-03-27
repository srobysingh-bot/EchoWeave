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
    async def check_stream_url(stream_base_url: str, allow_insecure: bool = False) -> dict[str, Any]:
        """Verify that the stream base URL is reachable and secure."""
        from app.ma.stream_resolver import is_valid_alexa_stream_url, STREAM_PATH_HINT
        if not stream_base_url:
            return {
                "key": "stream_url_valid",
                "status": "warn",
                "message": "Stream base URL not configured.",
            }
            
        if not is_valid_alexa_stream_url(stream_base_url, allow_insecure):
            return {
                "key": "stream_url_valid",
                "status": "fail",
                "message": "Stream URL is insecure (must be public HTTPS).",
            }
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.head(stream_base_url)
                if resp.status_code == 405:
                    resp = await client.get(stream_base_url)
            status = resp.status_code
            if 200 <= status < 400:
                return {
                    "key": "stream_url_valid",
                    "status": "ok",
                    "message": f"Stream URL is reachable with HTTP {status}.",
                }
            if status in (404, 405):
                return {
                    "key": "stream_url_valid",
                    "status": "warn",
                    "message": (
                        f"Base URL reachable; root returned HTTP {status}. "
                        f"This may be normal if stream paths are generated under {STREAM_PATH_HINT}."
                    ),
                }
            if 400 <= status < 500:
                return {
                    "key": "stream_url_valid",
                    "status": "warn",
                    "message": f"Stream URL is reachable but invalid (HTTP {status}).",
                }
            return {
                "key": "stream_url_valid",
                "status": "fail",
                "message": f"Stream URL service error (HTTP {status}).",
            }
        except Exception as exc:
            return {
                "key": "stream_url_valid",
                "status": "fail",
                "message": f"Stream URL unreachable: {exc}",
            }

    async def run_all(
        self,
        stream_base_url: str = "",
        allow_insecure: bool = False,
        include_stream_check: bool = True,
    ) -> list[dict[str, Any]]:
        """Run all MA-related health checks and return results."""
        results = [await self.check_reachable(), await self.check_auth()]
        if include_stream_check:
            results.append(await self.check_stream_url(stream_base_url, allow_insecure))
        return results
