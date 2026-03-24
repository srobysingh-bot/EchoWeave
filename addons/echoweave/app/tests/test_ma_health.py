"""Tests for MA health checker status mapping."""

from __future__ import annotations

import pytest

from app.ma.health import MAHealthChecker


class _GoodMAClient:
    async def ping(self) -> bool:
        return True

    async def validate_token(self) -> bool:
        return True


@pytest.mark.anyio
async def test_ma_health_ok_when_connection_and_auth_valid():
    checker = MAHealthChecker(_GoodMAClient())

    reachable = await checker.check_reachable()
    auth = await checker.check_auth()

    assert reachable["key"] == "ma_reachable"
    assert reachable["status"] == "ok"
    assert auth["key"] == "ma_auth_valid"
    assert auth["status"] == "ok"
