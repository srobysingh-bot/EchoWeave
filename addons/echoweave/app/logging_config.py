"""Structured logging configuration with secret redaction.

Call ``setup_logging()`` once at application startup to configure the root
logger with a JSON-style formatter and a filter that strips sensitive values.
"""

from __future__ import annotations

import logging
import re
import sys
from typing import Any

from app.core.constants import SECRET_FIELDS

# Regex that matches common secret patterns in log messages.
_SECRET_RE = re.compile(
    r"(?i)("
    + "|".join(re.escape(f) for f in SECRET_FIELDS)
    + r""")['":\s=]+['"]?([^'",\s}{)\]]{4,})""",
)


class SecretRedactingFilter(logging.Filter):
    """Logging filter that replaces secret values with ``****``."""

    def filter(self, record: logging.LogRecord) -> bool:
        if isinstance(record.msg, str):
            record.msg = self._redact(record.msg)
        if record.args:
            record.args = tuple(
                self._redact(a) if isinstance(a, str) else a for a in record.args
            ) if isinstance(record.args, tuple) else record.args
        return True

    @staticmethod
    def _redact(text: str) -> str:
        return _SECRET_RE.sub(r"\1=****", text)


class StructuredFormatter(logging.Formatter):
    """Simple structured log formatter (key=value style)."""

    def format(self, record: logging.LogRecord) -> str:
        base = super().format(record)
        return (
            f"ts={self.formatTime(record)} "
            f"level={record.levelname} "
            f"logger={record.name} "
            f"msg={base}"
        )


def _level_from_string(level: str) -> int:
    """Convert a string log-level name to a ``logging`` constant."""
    mapping: dict[str, int] = {
        "trace": logging.DEBUG,  # Python has no TRACE; map to DEBUG
        "debug": logging.DEBUG,
        "info": logging.INFO,
        "warning": logging.WARNING,
        "error": logging.ERROR,
        "critical": logging.CRITICAL,
    }
    return mapping.get(level.lower(), logging.INFO)


def setup_logging(level: str = "info", json_format: bool = False) -> None:
    """Configure root logger with redaction filter and structured format."""
    root = logging.getLogger()
    root.setLevel(_level_from_string(level))

    # Remove existing handlers to avoid duplicates on reload
    root.handlers.clear()

    handler = logging.StreamHandler(sys.stdout)
    handler.setLevel(_level_from_string(level))

    if json_format:
        handler.setFormatter(StructuredFormatter())
    else:
        handler.setFormatter(
            logging.Formatter(
                "%(asctime)s [%(levelname)-8s] %(name)s: %(message)s",
                datefmt="%Y-%m-%d %H:%M:%S",
            )
        )

    handler.addFilter(SecretRedactingFilter())
    root.addHandler(handler)

    # Quiet noisy third-party loggers
    for noisy in ("httpx", "httpcore", "uvicorn.access"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
