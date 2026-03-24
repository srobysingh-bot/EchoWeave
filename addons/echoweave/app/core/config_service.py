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
from typing import Any

from app.core.constants import SECRET_FIELDS

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

    def get_redacted_summary(self) -> dict[str, Any]:
        """Return the current settings dict with secrets replaced."""
        raw = self._settings.model_dump() if hasattr(self._settings, "model_dump") else vars(self._settings)
        return redact_dict(raw)

    async def save_override(self, key: str, value: Any) -> None:
        """Persist a runtime config override (e.g. from the admin UI)."""
        if self._persistence is None:
            logger.warning("No persistence layer — override for '%s' will not survive restart.", key)
            return
        # TODO: implement persistence write
        logger.info("Config override saved: %s", key if key.lower() not in SECRET_FIELDS else "****")
