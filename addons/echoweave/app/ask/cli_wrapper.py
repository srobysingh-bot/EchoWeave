"""Wrapper around the ASK CLI for skill management.

TODO: All methods in this module are stubs for Phase 1.  They will be
implemented once ASK CLI integration and AWS credential flows are set up.
"""

from __future__ import annotations

import logging
import shutil

logger = logging.getLogger(__name__)


def is_ask_cli_installed() -> bool:
    """Return ``True`` if the ASK CLI binary is found on ``$PATH``."""
    return shutil.which("ask") is not None


async def run_ask_command(args: list[str]) -> dict:
    """Run an ASK CLI command and capture stdout/stderr.

    TODO: Implement subprocess wrapper with timeout and secret redaction.
    """
    logger.warning("ASK CLI execution is not yet implemented. Args: %s", args)
    return {
        "success": False,
        "stdout": "",
        "stderr": "ASK CLI wrapper not implemented.",
        "returncode": -1,
    }
