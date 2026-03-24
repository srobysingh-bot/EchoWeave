"""Manage stored ASK credentials/material.

TODO: Phase 1 stub.  Credentials are stored in ``/data/ask/`` and are
never exposed to logs or UI.
"""

from __future__ import annotations

import logging
from pathlib import Path

logger = logging.getLogger(__name__)


class ASKCredentials:
    """Manage ASK credential files in the persistent data directory."""

    def __init__(self, data_dir: str) -> None:
        self._dir = Path(data_dir) / "ask"
        self._dir.mkdir(parents=True, exist_ok=True)

    @property
    def credentials_dir(self) -> Path:
        return self._dir

    def has_credentials(self) -> bool:
        """Return ``True`` if any credential files exist."""
        return any(self._dir.iterdir()) if self._dir.is_dir() else False

    def store_credential_file(self, filename: str, content: bytes) -> None:
        """Write a credential file (never log contents)."""
        path = self._dir / filename
        path.write_bytes(content)
        logger.info("Stored ASK credential file: %s", filename)

    def delete_all(self) -> None:
        """Remove all credential files."""
        for f in self._dir.glob("*"):
            f.unlink()
        logger.info("All ASK credentials deleted.")
