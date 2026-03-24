"""Bridge between add-on options, persistent config, and runtime settings.

This module is the single source of truth for "what config values should the
app use right now?"  It merges:
  1. Defaults from ``core.constants``.
  2. Values persisted in ``/data/config.json`` (via the storage layer).
  3. Environment variables exported by ``run.sh``.
  4. Values saved through the admin UI.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

from app.core.constants import SECRET_FIELDS
from app.storage.models import PersistedConfig

logger = logging.getLogger(__name__)


def redact_dict(data: dict[str, Any]) -> dict[str, Any]:
    """Return a shallow copy of *data* with secret values replaced by ``'****'``."""
    redacted: dict[str, Any] = {}
    for key, value in data.items():
        if key.lower() in SECRET_FIELDS or "token" in key.lower() or "password" in key.lower():
            redacted[key] = "****" if value else ""
        elif isinstance(value, dict):
            redacted[key] = redact_dict(value)
        else:
            redacted[key] = value
    return redacted


class ConfigService:
    """Merge and expose resolved configuration.

    Typically instantiated once during startup and registered in the
    ``ServiceRegistry``.
    """

    def __init__(self, settings: Any, persistence: Any | None = None) -> None:
        self._settings = settings
        self._persistence = persistence

    @property
    def settings(self) -> Any:
        return self._settings

    def _current_persisted(self) -> PersistedConfig:
        """Build a PersistedConfig snapshot from current runtime settings."""
        return PersistedConfig(
            ma_base_url=getattr(self._settings, "ma_base_url", "") or "",
            ma_token=getattr(self._settings, "ma_token", "") or "",
            public_base_url=getattr(self._settings, "public_base_url", "") or "",
            stream_base_url=getattr(self._settings, "stream_base_url", "") or "",
            locale=getattr(self._settings, "locale", "en-US") or "en-US",
            aws_default_region=getattr(self._settings, "aws_default_region", "us-east-1") or "us-east-1",
            log_level=getattr(self._settings, "log_level", "info") or "info",
            debug=bool(getattr(self._settings, "debug", False)),
            updated_at=datetime.utcnow(),
        )

    def get_redacted_summary(self) -> dict[str, Any]:
        """Return the current settings dict with secrets replaced."""
        raw = self._settings.model_dump() if hasattr(self._settings, "model_dump") else vars(self._settings)
        summary = redact_dict(raw)
        if raw.get("ma_token"):
            summary["ma_token"] = "**** (set)"
        return summary

    def save_persisted(self, config: PersistedConfig) -> PersistedConfig:
        """Persist and apply a complete config object."""
        if hasattr(self._settings, "apply_persisted"):
            self._settings.apply_persisted(config)
        if self._persistence is not None:
            self._persistence.save_config(config)
        return config

    def save_updates(self, updates: dict[str, Any]) -> PersistedConfig:
        """Persist selective config updates merged with existing runtime values."""
        filtered = {
            key: value
            for key, value in updates.items()
            if key in {
                "ma_base_url",
                "ma_token",
                "public_base_url",
                "stream_base_url",
                "locale",
                "aws_default_region",
                "log_level",
                "debug",
            }
        }
        merged = self._current_persisted().model_copy(update=filtered)
        merged.updated_at = datetime.utcnow()
        return self.save_persisted(merged)

    async def save_override(self, key: str, value: Any) -> None:
        """Persist a runtime config override (e.g. from the admin UI)."""
        if self._persistence is None:
            logger.warning("No persistence layer — override for '%s' will not survive restart.", key)
            return
        self.save_updates({key: value})
        logger.info("Config override saved: %s", key if key.lower() not in SECRET_FIELDS else "****")
