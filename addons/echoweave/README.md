# EchoWeave

**Alexa bridge backend for Music Assistant — Home Assistant add-on.**

## What EchoWeave Is

EchoWeave is a Home Assistant add-on that runs a backend bridge service between
[Music Assistant](https://music-assistant.io/) and Amazon Alexa devices. It:

1. Hosts the Alexa skill endpoint.
2. Connects to the Music Assistant API using long-lived tokens.
3. Stores playback/session state for Alexa devices.
4. Provides a local admin UI for setup, status, logs, and diagnostics.
5. Helps automate and validate Alexa skill setup.

### Architecture

```
┌─────────┐     HTTPS      ┌───────────┐     HTTP/WS     ┌──────────────────┐
│  Alexa  │ ──────────────▶ │ EchoWeave │ ──────────────▶ │ Music Assistant  │
│ Device  │ ◀────────────── │  Add-on   │ ◀────────────── │     Server       │
└─────────┘  Audio directives└───────────┘  Queue/stream   └──────────────────┘
      │                           │
      │  Fetches audio stream     │  Provides admin UI via
      ▼  from public HTTPS URL    │  HA ingress / reverse proxy
┌─────────────┐                   ▼
│ Stream CDN  │            ┌─────────────┐
│ / Proxy     │            │ HA Sidebar  │
└─────────────┘            └─────────────┘
```

**Important:** EchoWeave does *not* directly push audio to Alexa. Instead, it
responds to Alexa skill requests with playable HTTPS stream URLs. The Alexa
device then fetches and plays the stream itself.

## What EchoWeave Is Not

- Not a replacement for Music Assistant's native player support.
- Not a cloud-hosted shared Alexa skill.
- Not a full-feature Alexa media controller (yet).
- Not a Home Assistant custom integration (that comes later).

## Current Phase: 1 (Add-on Backend)

- ✅ Add-on scaffold & containerization
- ✅ FastAPI app with admin UI pages
- ✅ Music Assistant client with token auth
- ✅ Alexa request/response flow definitions
- ✅ Session/queue state management
- ✅ Diagnostics & health checks
- ⬜ Home Assistant custom integration (Phase 2)
- ⬜ Full ASK automation (Phase 2+)

## Requirements

- Home Assistant OS or Supervised installation
- Music Assistant server (reachable from HA host)
- Music Assistant long-lived API token
- Public HTTPS URL for Alexa webhook (reverse proxy)
- Public HTTPS URL for audio streams
- AWS developer account (for Alexa skill creation)

## Reverse Proxy

The Alexa webhook **must** be reachable via public HTTPS. Do **not** rely on
Home Assistant ingress for this — configure a reverse proxy (e.g., NGINX,
Caddy, Cloudflare Tunnel) to forward `https://your-domain/alexa` to the add-on
on port 5000.

## Development

```bash
cd addons/echoweave
pip install -r requirements.txt
python -m uvicorn app.main:app --host 0.0.0.0 --port 5000 --reload
```

Set environment variables or create `/data/options.json` for local testing:

```json
{
  "ma_base_url": "http://localhost:8095",
  "ma_token": "your-ma-token",
  "public_base_url": "https://your-public-domain.com",
  "stream_base_url": "https://your-stream-domain.com",
  "log_level": "debug",
  "debug": true,
  "allow_insecure_local_test": true
}
```

## Testing

```bash
pip install pytest pytest-asyncio pytest-cov
python -m pytest app/tests/ -v
```

## Known Limitations

- ASK CLI wrappers are stubbed; manual Alexa skill setup required in Phase 1.
- No Alexa request signature verification yet.
- Session store is JSON-file-backed (not a database).
- No multi-user / multi-device concurrent testing yet.

## License

Apache-2.0
