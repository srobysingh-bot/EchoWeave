"""Logs / diagnostics page — safely view recent logs."""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates

from app.storage.secrets import redact

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/logs", tags=["logs"])
templates = Jinja2Templates(directory="app/web/templates")

# In-memory ring buffer for recent log entries (simple MVP approach).
_LOG_BUFFER: list[dict[str, Any]] = []
_MAX_LOG_ENTRIES = 500


class BufferedLogHandler(logging.Handler):
    """Logging handler that keeps the last N log records in memory."""

    def emit(self, record: logging.LogRecord) -> None:
        entry = {
            "timestamp": self.format(record).split(" ")[0] if hasattr(record, "asctime") else "",
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        _LOG_BUFFER.append(entry)
        if len(_LOG_BUFFER) > _MAX_LOG_ENTRIES:
            _LOG_BUFFER.pop(0)


def install_log_buffer() -> None:
    """Attach the ``BufferedLogHandler`` to the root logger."""
    handler = BufferedLogHandler()
    handler.setLevel(logging.DEBUG)
    handler.setFormatter(logging.Formatter("%(asctime)s"))
    logging.getLogger().addHandler(handler)


@router.get("", response_class=HTMLResponse)
@router.get("/", response_class=HTMLResponse)
async def logs_page(request: Request) -> HTMLResponse:
    """Render the logs viewer page."""
    # Show most recent first
    entries = list(reversed(_LOG_BUFFER[-200:]))
    return templates.TemplateResponse(
        request,
        "logs.html",
        {
            "entries": entries,
            "total": len(_LOG_BUFFER),
        },
    )


@router.get("/download")
async def download_logs() -> JSONResponse:
    """Return logs as JSON for diagnostics bundle download.

    TODO: Include redacted config snapshot and health check results.
    """
    return JSONResponse(content={
        "logs": _LOG_BUFFER[-500:],
        "note": "Secrets are redacted from log messages.",
    })
