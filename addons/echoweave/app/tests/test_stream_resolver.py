"""Tests for stream resolver hardening."""

import pytest
from app.ma.stream_resolver import StreamResolver, is_valid_alexa_stream_url
from app.core.exceptions import StreamResolutionError
from app.ma.models import MAQueueItem

def test_is_valid_alexa_stream_url():
    # Strict mode
    assert is_valid_alexa_stream_url("https://example.com/stream", allow_insecure=False)
    assert not is_valid_alexa_stream_url("http://example.com/stream", allow_insecure=False)
    assert not is_valid_alexa_stream_url("https://192.168.1.50/stream", allow_insecure=False)
    assert not is_valid_alexa_stream_url("https://10.0.0.1/s", allow_insecure=False)
    assert not is_valid_alexa_stream_url("https://localhost:5000/stream", allow_insecure=False)
    assert not is_valid_alexa_stream_url("https://127.0.0.1", allow_insecure=False)
    
    # Insecure mode bypass
    assert is_valid_alexa_stream_url("http://example.com", allow_insecure=True)
    assert is_valid_alexa_stream_url("http://192.168.1.50", allow_insecure=True)
    assert is_valid_alexa_stream_url("http://localhost", allow_insecure=True)


def test_resolver_rejects_insecure_base():
    resolver = StreamResolver("http://192.168.1.50", allow_insecure=False)
    item = MAQueueItem(queue_id="q1", queue_item_id="1", name="Test", uri="test")
    with pytest.raises(StreamResolutionError) as exc:
        resolver.resolve(item)
    assert "fails Alexa public HTTPS policy" in str(exc.value)

def test_resolver_accepts_insecure_if_allowed():
    resolver = StreamResolver("http://192.168.1.50", allow_insecure=True)
    item = MAQueueItem(queue_id="q1", queue_item_id="1", name="Test", uri="test")
    url = resolver.resolve(item)
    assert url.startswith("http://192.168.1.50/stream/")
