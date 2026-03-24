"""Produce a support/diagnostics bundle with redacted config and logs."""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

from app.storage.secrets import redact_dict

logger = logging.getLogger(__name__)


class DiagnosticsReporter:
    """Generate a redacted diagnostics bundle for support."""

    def __init__(self, config_service=None, health_service=None, log_buffer=None) -> None:
        self._config = config_service
        self._health = health_service
        self._log_buffer = log_buffer or []

    async def generate_bundle(self) -> dict[str, Any]:
        """Build a JSON-serialisable diagnostics bundle."""
        bundle: dict[str, Any] = {
            "generated_at": datetime.utcnow().isoformat() + "Z",
            "config": {},
            "health": {},
            "recent_logs": [],
        }

        # Redacted config
        if self._config:
            bundle["config"] = self._config.get_redacted_summary()

        # Latest health results
        if self._health and self._health.last_result:
            bundle["health"] = {
                "overall": self._health.overall_status,
                "checks": [c.model_dump() for c in self._health.last_result.checks],
            }

        # Last 100 log entries
        bundle["recent_logs"] = self._log_buffer[-100:]

        return bundle
