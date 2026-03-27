from __future__ import annotations


class TenantRegistry:
    """Minimal placeholder registry for Sprint 1 wiring."""

    def __init__(self) -> None:
        self._tenants: set[str] = set()

    def mark_seen(self, tenant_id: str) -> None:
        if tenant_id:
            self._tenants.add(tenant_id)

    def exists(self, tenant_id: str) -> bool:
        return tenant_id in self._tenants


tenant_registry = TenantRegistry()
