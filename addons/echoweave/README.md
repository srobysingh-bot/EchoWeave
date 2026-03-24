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

## Installation (GitHub Repository)

EchoWeave is distributed as a custom Home Assistant add-on repository.

1. Navigate to your Home Assistant instance.
2. Go to **Settings** > **Add-ons**.
3. Click on the **Add-on Store** button.
4. Click the three-dot menu (**⋮**) in the top right corner and select **Repositories**.
5. Paste the GitHub URL: `https://github.com/srobysingh-bot/EchoWeave` and click **Add**.
6. Close the dialog, scroll down, find **EchoWeave Home Assistant Add-ons**, and click **Install**.

## First-Run Setup

Once installed and started, click **Open Web UI** to configure the bridge:

1. **Music Assistant Settings:** Enter your MA Server URL (e.g. `http://homeassistant:8095`) and a Long-Lived Access Token.
2. **Public Base URLs:** Enter your public HTTPS proxy URL for the Alexa Webhook (e.g., `https://echoweave.yourdomain.com`) and for audio streaming.
3. Click **Validate and Save**. The setup wizard will ping the endpoints to ensure readiness.

## Important Notes & Constraints

*   **Experimental Status:** EchoWeave is currently an experimental standalone bridge backend.
*   **Public HTTPS / SSL Required:** Alexa AudioPlayer skills **require** a valid, public HTTPS endpoint secured by a trusted SSL certificate. You *must* have a reverse proxy (like Nginx Proxy Manager or Cloudflare Tunnels) exposing the add-on's port to the public internet. Local IP addresses, unencrypted HTTP, and internal hostnames (like `.local`) will be rejected by Alexa and by EchoWeave's internal security validations.

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
