"""Central access point for initialised services and clients.

The registry is populated during application startup and provides a single
place for route handlers and background tasks to obtain shared instances
(MA client, persistence layer, health service, etc.) without circular imports.
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


class ServiceRegistry:
    """Lightweight service locator initialised at app startup."""

    def __init__(self) -> None:
        self._services: dict[str, Any] = {}

    # -- registration --------------------------------------------------------

    def register(self, name: str, instance: Any) -> None:
        """Register a service instance under *name*."""
        if name in self._services:
            logger.warning("Service '%s' is being replaced in the registry.", name)
        self._services[name] = instance
        logger.debug("Registered service: %s", name)

    # -- retrieval -----------------------------------------------------------

    def get(self, name: str) -> Any:
        """Return a previously registered service or raise ``KeyError``."""
        try:
            return self._services[name]
        except KeyError:
            raise KeyError(
                f"Service '{name}' not found in registry. "
                "Was it registered during startup?"
            ) from None

    def get_optional(self, name: str) -> Any | None:
        """Return a service or ``None`` if it has not been registered."""
        return self._services.get(name)

    # -- lifecycle -----------------------------------------------------------

    async def shutdown(self) -> None:
        """Call ``close()`` on every service that exposes it."""
        for name, svc in self._services.items():
            close = getattr(svc, "close", None)
            if callable(close):
                logger.debug("Closing service: %s", name)
                try:
                    result = close()
                    # Support both sync and async close()
                    if hasattr(result, "__await__"):
                        await result
                except Exception:
                    logger.exception("Error closing service '%s'", name)
        self._services.clear()


# Module-level singleton — import and use directly.
registry = ServiceRegistry()
