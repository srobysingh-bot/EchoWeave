"""FastAPI dependency-injection helpers.

Each ``get_*`` function is designed to be used with ``fastapi.Depends(...)``
so route handlers receive fully-initialised service instances.
"""

from __future__ import annotations

from functools import lru_cache

from app.settings import Settings, load_settings
from app.core.service_registry import registry


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return the singleton ``Settings`` instance."""
    return load_settings()


def get_persistence():
    """Return the ``PersistenceService`` from the service registry."""
    return registry.get("persistence")


def get_ma_client():
    """Return the ``MusicAssistantClient`` from the service registry."""
    return registry.get("ma_client")


def get_health_service():
    """Return the ``HealthService`` from the service registry."""
    return registry.get("health")


def get_config_service():
    """Return the ``ConfigService`` from the service registry."""
    return registry.get("config_service")
