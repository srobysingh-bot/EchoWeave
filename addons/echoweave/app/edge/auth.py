from __future__ import annotations

import hashlib
import hmac
import time


def sign_edge_request(*, shared_secret: str, method: str, path: str, timestamp: int | None = None) -> tuple[str, str]:
    ts = str(timestamp or int(time.time()))
    payload = f"{ts}:{method.upper()}:{path}"
    signature = hmac.new(shared_secret.encode("utf-8"), payload.encode("utf-8"), hashlib.sha256).digest()
    return ts, _base64url(signature)


def verify_edge_request(*, shared_secret: str, method: str, path: str, timestamp: str, signature: str, max_age_seconds: int = 60) -> bool:
    if not shared_secret or not timestamp or not signature:
        return False

    try:
        ts_value = int(timestamp)
    except ValueError:
        return False

    now = int(time.time())
    if abs(now - ts_value) > max_age_seconds:
        return False

    payload = f"{timestamp}:{method.upper()}:{path}"
    expected = hmac.new(shared_secret.encode("utf-8"), payload.encode("utf-8"), hashlib.sha256).digest()
    return hmac.compare_digest(_base64url(expected), signature)


def _base64url(value: bytes) -> str:
    import base64

    return base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")
