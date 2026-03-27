"""Central configuration loader.

Reads add-on options from ``/data/options.json`` (Home Assistant convention)
and falls back to environment variables prefixed with ``ECHOWEAVE_``.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Optional

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


TRACKED_CONFIG_FIELDS: tuple[str, ...] = (
    "mode",
    "backend_url",
    "worker_base_url",
    "tunnel_base_url",
    "edge_shared_secret",
    "connector_id",
    "connector_secret",
    "tenant_id",
    "home_id",
    "alexa_source_queue_id",
    "ma_base_url",
    "ma_token",
    "public_base_url",
    "stream_base_url",
    "locale",
    "aws_default_region",
    "log_level",
    "debug",
    "allow_insecure_local_test",
)


def _is_set(value: Any) -> bool:
    if isinstance(value, str):
        return bool(value.strip())
    return value is not None


def _load_options_json() -> dict:
    """Try to read HA add-on options from the well-known path."""
    options_file = Path(os.getenv("ECHOWEAVE_DATA_DIR", DEFAULT_DATA_DIR)) / "options.json"
    if options_file.is_file():
        with open(options_file, "r", encoding="utf-8") as fh:
            return json.load(fh)
    return {}


def load_addon_options() -> dict[str, Any]:
    """Public helper returning Home Assistant add-on options."""
    return _load_options_json()


class Settings(BaseSettings):
    """Typed, validated application settings."""

    # -- Runtime mode --------------------------------------------------------
    mode: str = "legacy"

    # -- Connector mode ------------------------------------------------------
    backend_url: str = ""
    worker_base_url: str = ""
    tunnel_base_url: str = ""
    edge_shared_secret: str = ""
    connector_id: str = ""
    connector_secret: str = ""
    tenant_id: str = ""
    home_id: str = ""
    alexa_source_queue_id: str = ""

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

    @field_validator(
        "backend_url",
        "worker_base_url",
        "tunnel_base_url",
        "ma_base_url",
        "public_base_url",
        "stream_base_url",
    )
    @classmethod
    def _strip_trailing_slash(cls, v: str) -> str:
        return v.rstrip("/") if v else v

    @field_validator(
        "connector_id",
        "connector_secret",
        "tenant_id",
        "home_id",
        "edge_shared_secret",
        "alexa_source_queue_id",
    )
    @classmethod
    def _strip_connector_fields(cls, v: str) -> str:
        return v.strip() if isinstance(v, str) else v

    @field_validator("mode")
    @classmethod
    def _validate_mode(cls, v: str) -> str:
        mode = (v or "legacy").strip().lower()
        if mode not in {"legacy", "connector", "edge"}:
            raise ValueError("mode must be one of ['legacy', 'connector', 'edge']")
        return mode

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
    def is_connector_mode(self) -> bool:
        return self.mode == "connector"

    @property
    def is_edge_mode(self) -> bool:
        return self.mode == "edge"

    @property
    def ma_configured(self) -> bool:
        return bool(self.ma_base_url and self.ma_token)

    @property
    def connector_configured(self) -> bool:
        if self.is_edge_mode:
            return bool(
                self.worker_base_url
                and self.tunnel_base_url
                and self.edge_shared_secret
                and self.connector_id
                and self.connector_secret
                and self.tenant_id
                and self.home_id
            )

        return bool(
            self.backend_url
            and self.connector_id
            and self.connector_secret
            and self.tenant_id
            and self.home_id
        )

    @property
    def connector_settings(self) -> dict[str, str]:
        return {
            "backend_url": self.backend_url,
            "worker_base_url": self.worker_base_url,
            "tunnel_base_url": self.tunnel_base_url,
            "edge_shared_secret": self.edge_shared_secret,
            "connector_id": self.connector_id,
            "connector_secret": self.connector_secret,
            "tenant_id": self.tenant_id,
            "home_id": self.home_id,
            "alexa_source_queue_id": self.alexa_source_queue_id,
        }

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

    def apply_persisted(self, persisted: Any, *, fields: tuple[str, ...] | None = None) -> None:
        """Overlay values from a PersistedConfig for set fields."""
        if not persisted:
            return
        target_fields = fields or TRACKED_CONFIG_FIELDS
        for field in target_fields:
            value = getattr(persisted, field, None)
            if _is_set(value):
                setattr(self, field, value)


def load_settings() -> Settings:
    """Build a ``Settings`` instance merging options.json and env vars."""
    options = _load_options_json()
    return Settings(**options)
