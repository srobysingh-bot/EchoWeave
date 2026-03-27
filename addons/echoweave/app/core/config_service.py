"""Bridge between add-on options, persistent config, and runtime settings.

This module is the single source of truth for "what config values should the
app use right now?"  It merges:
  1. Defaults from ``core.constants``.
  2. Values persisted in ``/data/config.json`` (via the storage layer).
  3. Environment variables exported by ``run.sh``.
  4. Values saved through the admin UI.
"""

from __future__ import annotations

import os
import logging
from datetime import datetime
from typing import Any
from urllib.parse import urlparse

from app.core.constants import SECRET_FIELDS
from app.storage.models import PersistedConfig
from app.settings import TRACKED_CONFIG_FIELDS, load_addon_options

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
        self._field_sources: dict[str, str] = {}

    @staticmethod
    def _is_set(value: Any) -> bool:
        if isinstance(value, str):
            return bool(value.strip())
        return value is not None

    @staticmethod
    def _env_name(field: str) -> str:
        return f"ECHOWEAVE_{field.upper()}"

    @staticmethod
    def _normalise_url_for_log(value: str) -> str:
        if not value:
            return ""
        parsed = urlparse(value)
        if not parsed.scheme or not parsed.hostname:
            return "<invalid-url>"
        if parsed.port:
            return f"{parsed.scheme}://{parsed.hostname}:{parsed.port}"
        return f"{parsed.scheme}://{parsed.hostname}"

    def resolve_effective(self) -> dict[str, str]:
        """Resolve field sources with precedence addon > env > persisted > default."""
        addon_options = load_addon_options()
        persisted = self._persistence.load_config() if self._persistence else None
        sources: dict[str, str] = {}

        for field in TRACKED_CONFIG_FIELDS:
            addon_value = addon_options.get(field)
            env_name = self._env_name(field)
            env_value = os.getenv(env_name)
            persisted_value = getattr(persisted, field, None) if persisted else None

            if field in addon_options and self._is_set(addon_value):
                setattr(self._settings, field, addon_value)
                sources[field] = "addon_options"
                continue

            if env_name in os.environ and self._is_set(env_value):
                sources[field] = "environment"
                continue

            if self._is_set(persisted_value):
                setattr(self._settings, field, persisted_value)
                sources[field] = "persisted_config"
                continue

            sources[field] = "default"

        self._field_sources = sources
        self._repair_persisted_if_needed(persisted)
        return sources

    def _repair_persisted_if_needed(self, persisted: PersistedConfig | None) -> None:
        if self._persistence is None:
            return

        effective = self._current_persisted()
        if persisted is None:
            self._persistence.save_config(effective)
            return

        changed = False
        for field in TRACKED_CONFIG_FIELDS:
            if getattr(persisted, field, None) != getattr(effective, field, None):
                changed = True
                break

        if changed:
            logger.info("Persisted config differed from effective runtime config; syncing repaired values.")
            self._persistence.save_config(effective)

    @property
    def settings(self) -> Any:
        return self._settings

    @property
    def field_sources(self) -> dict[str, str]:
        return dict(self._field_sources)

    def _current_persisted(self) -> PersistedConfig:
        """Build a PersistedConfig snapshot from current runtime settings."""
        return PersistedConfig(
            mode=getattr(self._settings, "mode", "legacy") or "legacy",
            backend_url=getattr(self._settings, "backend_url", "") or "",
            connector_id=getattr(self._settings, "connector_id", "") or "",
            connector_secret=getattr(self._settings, "connector_secret", "") or "",
            tenant_id=getattr(self._settings, "tenant_id", "") or "",
            home_id=getattr(self._settings, "home_id", "") or "",
            ma_base_url=getattr(self._settings, "ma_base_url", "") or "",
            ma_token=getattr(self._settings, "ma_token", "") or "",
            public_base_url=getattr(self._settings, "public_base_url", "") or "",
            stream_base_url=getattr(self._settings, "stream_base_url", "") or "",
            locale=getattr(self._settings, "locale", "en-US") or "en-US",
            aws_default_region=getattr(self._settings, "aws_default_region", "us-east-1") or "us-east-1",
            log_level=getattr(self._settings, "log_level", "info") or "info",
            debug=bool(getattr(self._settings, "debug", False)),
            allow_insecure_local_test=bool(getattr(self._settings, "allow_insecure_local_test", False)),
            updated_at=datetime.utcnow(),
        )

    def get_redacted_summary(self) -> dict[str, Any]:
        """Return the current settings dict with secrets replaced."""
        raw = self._settings.model_dump() if hasattr(self._settings, "model_dump") else vars(self._settings)
        summary = redact_dict(raw)
        if raw.get("ma_token"):
            summary["ma_token"] = "**** (set)"
        return summary

    def get_effective_with_sources(self) -> dict[str, dict[str, Any]]:
        """Return resolved effective values and source labels for UI/status pages."""
        result: dict[str, dict[str, Any]] = {}
        raw = self._settings.model_dump() if hasattr(self._settings, "model_dump") else vars(self._settings)
        for field in TRACKED_CONFIG_FIELDS:
            result[field] = {
                "value": raw.get(field, ""),
                "source": self._field_sources.get(field, "default"),
            }
        return result

    def log_effective_runtime(self) -> None:
        """Log the final runtime config values used by health and status checks."""
        logger.info(
            "Effective runtime config: mode=%s source=%s",
            getattr(self._settings, "mode", "legacy"),
            self._field_sources.get("mode", "default"),
        )
        logger.info(
            "Effective runtime config: backend_url=%s source=%s",
            self._normalise_url_for_log(getattr(self._settings, "backend_url", "") or ""),
            self._field_sources.get("backend_url", "default"),
        )
        logger.info(
            "Effective runtime config: ma_base_url=%s source=%s",
            self._normalise_url_for_log(getattr(self._settings, "ma_base_url", "") or ""),
            self._field_sources.get("ma_base_url", "default"),
        )
        logger.info(
            "Effective runtime config: public_base_url=%s source=%s",
            self._normalise_url_for_log(getattr(self._settings, "public_base_url", "") or ""),
            self._field_sources.get("public_base_url", "default"),
        )
        logger.info(
            "Effective runtime config: stream_base_url=%s source=%s",
            self._normalise_url_for_log(getattr(self._settings, "stream_base_url", "") or ""),
            self._field_sources.get("stream_base_url", "default"),
        )
        logger.info(
            "Effective runtime config: allow_insecure_local_test=%s source=%s",
            bool(getattr(self._settings, "allow_insecure_local_test", False)),
            self._field_sources.get("allow_insecure_local_test", "default"),
        )

    def save_persisted(self, config: PersistedConfig) -> PersistedConfig:
        """Persist and apply a complete config object."""
        if hasattr(self._settings, "apply_persisted"):
            self._settings.apply_persisted(config)
        self._field_sources.update({field: "persisted_config" for field in TRACKED_CONFIG_FIELDS if hasattr(config, field)})
        if self._persistence is not None:
            self._persistence.save_config(config)
        return config

    def save_updates(self, updates: dict[str, Any]) -> PersistedConfig:
        """Persist selective config updates merged with existing runtime values."""
        filtered = {
            key: value
            for key, value in updates.items()
            if key in {
                "mode",
                "backend_url",
                "connector_id",
                "connector_secret",
                "tenant_id",
                "home_id",
                "ma_base_url",
                "ma_token",
                "public_base_url",
                "stream_base_url",
                "locale",
                "aws_default_region",
                "log_level",
                "debug",
                "allow_insecure_local_test",
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
