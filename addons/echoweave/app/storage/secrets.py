"""Secret handling helpers: redaction, wrapping, safe display."""

from __future__ import annotations

from app.core.constants import SECRET_FIELDS


def redact(value: str, visible_chars: int = 4) -> str:
    """Return a redacted version of *value*, showing only the last few chars.

    >>> redact("my-super-secret-token-12345")
    '****2345'
    >>> redact("")
    ''
    >>> redact("ab")
    '****'
    """
    if not value:
        return ""
    if len(value) <= visible_chars:
        return "****"
    return "****" + value[-visible_chars:]


def is_secret_key(key: str) -> bool:
    """Return ``True`` if *key* looks like a secret field name."""
    lower = key.lower()
    return lower in SECRET_FIELDS or any(s in lower for s in ("token", "password", "secret", "cookie"))


def redact_dict(data: dict, visible_chars: int = 4) -> dict:
    """Recursively redact secret values in a dict."""
    result: dict = {}
    for key, value in data.items():
        if is_secret_key(key):
            result[key] = redact(str(value), visible_chars) if value else ""
        elif isinstance(value, dict):
            result[key] = redact_dict(value, visible_chars)
        else:
            result[key] = value
    return result
