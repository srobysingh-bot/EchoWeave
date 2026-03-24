"""Aggregate subsystem health checks and produce an overall result."""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

from app.storage.models import HealthCacheEntry, HealthCacheModel

logger = logging.getLogger(__name__)


class HealthService:
    """Run all registered subsystem checks and aggregate results."""

    def __init__(self) -> None:
        self._checks: list[Any] = []
        self._cache: HealthCacheModel | None = None

    def register_check(self, check_fn) -> None:
        """Register an async callable that returns ``dict(key, status, message)``."""
        self._checks.append(check_fn)

    async def run_all(self) -> HealthCacheModel:
        """Execute every registered check and return aggregated results."""
        entries: list[HealthCacheEntry] = []
        for check_fn in self._checks:
            try:
                result = await check_fn()
                if isinstance(result, list):
                    for r in result:
                        entries.append(HealthCacheEntry(**r))
                elif isinstance(result, dict):
                    entries.append(HealthCacheEntry(**result))
            except Exception as exc:
                logger.exception("Health check failed: %s", check_fn)
                entries.append(HealthCacheEntry(
                    key=getattr(check_fn, "__name__", "unknown"),
                    status="fail",
                    message=f"Check raised exception: {exc}",
                ))

        self._cache = HealthCacheModel(checks=entries, updated_at=datetime.utcnow())
        return self._cache

    @property
    def last_result(self) -> HealthCacheModel | None:
        return self._cache

    @property
    def overall_status(self) -> str:
        if self._cache is None:
            return "unknown"
        statuses = {c.status for c in self._cache.checks}
        if "fail" in statuses:
            return "fail"
        if "warn" in statuses:
            return "degraded"
        return "ok"
