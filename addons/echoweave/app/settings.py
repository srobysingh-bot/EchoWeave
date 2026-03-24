"""Central configuration loader.

Reads add-on options from ``/data/options.json`` (Home Assistant convention)
and falls back to environment variables prefixed with ``ECHOWEAVE_``.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Optional

from pydantic import field_validator, model_validator
from pydantic_settings import BaseSettings

from app.core.constants import (
    DEFAULT_AWS_REGION,
    DEFAULT_DATA_DIR,
    DEFAULT_LOCALE,
    DEFAULT_LOG_LEVEL,
    DEFAULT_PORT,
    DEFAULT_UI_USERNAME,
)


def _load_options_json() -> dict:
    """Try to read HA add-on options from the well-known path."""
    options_file = Path(os.getenv("ECHOWEAVE_DATA_DIR", DEFAULT_DATA_DIR)) / "options.json"
    if options_file.is_file():
        with open(options_file, "r", encoding="utf-8") as fh:
            return json.load(fh)
    return {}


class Settings(BaseSettings):
    """Typed, validated application settings."""

    # -- Music Assistant -----------------------------------------------------
    ma_base_url: str = ""
    ma_token: str = ""

    # -- Public endpoints ----------------------------------------------------
    public_base_url: str = ""
    stream_base_url: str = ""

    # -- Admin UI auth -------------------------------------------------------
    ui_username: str = DEFAULT_UI_USERNAME
    ui_password: str = ""

    # -- AWS / Alexa ---------------------------------------------------------
    aws_default_region: str = DEFAULT_AWS_REGION
    locale: str = DEFAULT_LOCALE

    # -- Runtime -------------------------------------------------------------
    log_level: str = DEFAULT_LOG_LEVEL
    debug: bool = False
    allow_insecure_local_test: bool = False
    port: int = DEFAULT_PORT
    data_dir: str = DEFAULT_DATA_DIR

    # -- Ingress (set by HA at runtime) --------------------------------------
    ingress_path: Optional[str] = None

    model_config = {
        "env_prefix": "ECHOWEAVE_",
        "env_file": ".env",
        "env_file_encoding": "utf-8",
        "extra": "ignore",
    }

    # -- validators ----------------------------------------------------------

    @field_validator("ma_base_url", "public_base_url", "stream_base_url")
    @classmethod
    def _strip_trailing_slash(cls, v: str) -> str:
        return v.rstrip("/") if v else v

    @field_validator("log_level")
    @classmethod
    def _normalise_log_level(cls, v: str) -> str:
        allowed = {"trace", "debug", "info", "warning", "error", "critical"}
        normalised = v.lower().strip()
        if normalised not in allowed:
            raise ValueError(f"log_level must be one of {sorted(allowed)}, got '{v}'")
        return normalised

    @model_validator(mode="after")
    def _warn_insecure(self) -> "Settings":
        if self.allow_insecure_local_test and not self.debug:
            import warnings
            warnings.warn(
                "allow_insecure_local_test is enabled without debug mode — "
                "this is dangerous outside development.",
                stacklevel=2,
            )
        return self

    # -- helpers -------------------------------------------------------------

    @property
    def ma_configured(self) -> bool:
        return bool(self.ma_base_url and self.ma_token)

    @property
    def public_configured(self) -> bool:
        return bool(self.public_base_url)

    @property
    def stream_configured(self) -> bool:
        return bool(self.stream_base_url)

    @property
    def ui_auth_enabled(self) -> bool:
        return bool(self.ui_password)

    @property
    def data_path(self) -> Path:
        return Path(self.data_dir)


def load_settings() -> Settings:
    """Build a ``Settings`` instance merging options.json and env vars."""
    options = _load_options_json()
    return Settings(**options)
