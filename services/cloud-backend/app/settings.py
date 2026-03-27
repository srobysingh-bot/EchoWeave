from __future__ import annotations

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    app_name: str = "EchoWeave Cloud Backend"
    app_version: str = "0.1.0"
    log_level: str = "info"

    model_config = {
        "env_prefix": "ECHOWEAVE_CLOUD_",
        "extra": "ignore",
    }


settings = Settings()
