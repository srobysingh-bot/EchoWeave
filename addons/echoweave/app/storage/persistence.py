"""JSON-file-backed persistent state management.

All durable state lives under the add-on's ``/data`` directory (mapped by
Home Assistant).  This module provides simple read/write helpers that
serialise Pydantic models to JSON files.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import TypeVar, Type

from pydantic import BaseModel

from app.core.constants import (
    FILE_CONFIG,
    FILE_HEALTH_CACHE,
    FILE_SKILL_META,
)
from app.core.exceptions import StorageError
from app.storage.models import (
    HealthCacheModel,
    PersistedConfig,
    SessionRecord,
    SkillMetadata,
)

logger = logging.getLogger(__name__)
T = TypeVar("T", bound=BaseModel)


class PersistenceService:
    """Read/write Pydantic models as JSON files in the data directory."""

    def __init__(self, data_dir: str | Path) -> None:
        self._root = Path(data_dir)
        self._root.mkdir(parents=True, exist_ok=True)
        self._sessions_dir = self._root / "sessions"
        self._sessions_dir.mkdir(exist_ok=True)

    # -- generic helpers -----------------------------------------------------

    def _read_model(self, filename: str, model_cls: Type[T]) -> T | None:
        path = self._root / filename
        if not path.is_file():
            return None
        try:
            with open(path, "r", encoding="utf-8") as fh:
                return model_cls.model_validate_json(fh.read())
        except Exception as exc:
            logger.error("Failed to read %s: %s", path, exc)
            return None

    def _write_model(self, filename: str, model: BaseModel) -> None:
        path = self._root / filename
        try:
            with open(path, "w", encoding="utf-8") as fh:
                fh.write(model.model_dump_json(indent=2))
        except Exception as exc:
            raise StorageError(f"Failed to write {path}: {exc}") from exc

    # -- config --------------------------------------------------------------

    def load_config(self) -> PersistedConfig | None:
        return self._read_model(FILE_CONFIG, PersistedConfig)

    def save_config(self, config: PersistedConfig) -> None:
        self._write_model(FILE_CONFIG, config)

    # -- health cache --------------------------------------------------------

    def load_health_cache(self) -> HealthCacheModel | None:
        return self._read_model(FILE_HEALTH_CACHE, HealthCacheModel)

    def save_health_cache(self, cache: HealthCacheModel) -> None:
        self._write_model(FILE_HEALTH_CACHE, cache)

    # -- skill metadata ------------------------------------------------------

    def load_skill_metadata(self) -> SkillMetadata | None:
        return self._read_model(FILE_SKILL_META, SkillMetadata)

    def save_skill_metadata(self, meta: SkillMetadata) -> None:
        self._write_model(FILE_SKILL_META, meta)

    # -- sessions ------------------------------------------------------------

    def load_session(self, device_id: str) -> SessionRecord | None:
        safe = device_id.replace("/", "_").replace("\\", "_")
        path = self._sessions_dir / f"{safe}.json"
        if not path.is_file():
            return None
        try:
            with open(path, "r", encoding="utf-8") as fh:
                return SessionRecord.model_validate_json(fh.read())
        except Exception as exc:
            logger.error("Failed to read session for device %s: %s", device_id, exc)
            return None

    def save_session(self, session: SessionRecord) -> None:
        safe = session.device_id.replace("/", "_").replace("\\", "_")
        path = self._sessions_dir / f"{safe}.json"
        try:
            with open(path, "w", encoding="utf-8") as fh:
                fh.write(session.model_dump_json(indent=2))
        except Exception as exc:
            raise StorageError(f"Failed to write session: {exc}") from exc

    def list_sessions(self) -> list[SessionRecord]:
        sessions: list[SessionRecord] = []
        for file in self._sessions_dir.glob("*.json"):
            try:
                with open(file, "r", encoding="utf-8") as fh:
                    sessions.append(SessionRecord.model_validate_json(fh.read()))
            except Exception:
                logger.warning("Skipping corrupt session file: %s", file.name)
        return sessions

    def delete_session(self, device_id: str) -> None:
        safe = device_id.replace("/", "_").replace("\\", "_")
        path = self._sessions_dir / f"{safe}.json"
        path.unlink(missing_ok=True)
