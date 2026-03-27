# EchoWeave

Alexa bridge backend for Music Assistant as a Home Assistant add-on.

## What EchoWeave Is

EchoWeave runs local services for Music Assistant integration and connector duties. In production, public Alexa ingress is handled by the edge worker. The add-on:

1. Connects to Music Assistant with long-lived token auth.
2. Maintains local configuration, diagnostics, and admin UI.
3. In edge mode, maintains outbound connector websocket to the Worker and Durable Object.
4. Exposes secure local stream origin route for Worker proxy.
5. Preserves legacy and connector modes for compatibility.

### Edge-First Architecture

```
┌─────────┐   HTTPS   ┌──────────────────┐   WS+Command   ┌───────────────┐
│  Alexa  │ ────────▶ │ services/edge-   │ ─────────────▶ │ EchoWeave     │
│ Device  │ ◀──────── │ worker           │ ◀───────────── │ Add-on (edge) │
└─────────┘ directives└──────────────────┘ responses       └──────┬────────┘
  │                                      │                     │
  │ stream fetch from Worker             │ stream proxy        │ resolve queue/item/stream
  ▼                                      ▼                     ▼
┌──────────────────┐                 ┌────────────────────┐   ┌──────────────────┐
│ /v1/stream/:token│ ──────────────▶ │ /edge/stream/...   │ ─▶│ Music Assistant  │
└──────────────────┘                 └────────────────────┘   └──────────────────┘
```

Important: Alexa is the playback device. The add-on resolves media context from Music Assistant and the Worker returns AudioPlayer.Play with signed stream token URL.

## Runtime Modes

- legacy: direct add-on Alexa ingress and legacy stream handling.
- connector: legacy cloud-backend heartbeat polling connector flow.
- edge: edge worker ingress plus persistent outbound connector websocket and secure local edge stream route.

## Installation (GitHub Repository)

EchoWeave is distributed as a custom Home Assistant add-on repository.

1. Navigate to your Home Assistant instance.
2. Go to **Settings** > **Add-ons**.
3. Click on the **Add-on Store** button.
4. Click the three-dot menu (**⋮**) in the top right corner and select **Repositories**.
5. Paste the GitHub URL: `https://github.com/srobysingh-bot/EchoWeave` and click **Add**.
6. Close the dialog, scroll down, find **EchoWeave Home Assistant Add-ons**, and click **Install**.

### Version Updates In Home Assistant

- EchoWeave now sets `auto_update: true`, so Home Assistant can auto-apply new add-on versions after they are detected.
- For custom repositories, Home Assistant may cache metadata. To see the newest version quickly:
  1. Open **Add-on Store**.
  2. Open the top-right menu (**⋮**).
  3. Click **Check for updates** (or reload repositories).
- The **Current version** field on the add-on info page shows the installed version; it changes after update/restart.

## First-Run Setup

Once installed and started, click **Open Web UI** to configure the bridge:

1. **Music Assistant Settings:** Enter your MA Server URL (e.g. `http://homeassistant:8095`) and a Long-Lived Access Token.
2. **Public Base URLs:** Enter your public HTTPS proxy URL for the Alexa Webhook (e.g., `https://echoweave.yourdomain.com`) and for audio streaming.
3. Click **Validate and Save**. The setup wizard will ping the endpoints to ensure readiness.

### Phase 1: Manual Alexa Skill Setup

Completing the setup checklist in Phase 1 requires manually creating and configuring an Alexa skill:

1. Go to the [Amazon Developer Console](https://developer.amazon.com/alexa/console/ask).
2. Create a new **Alexa Skills Kit (ASK)** skill with a custom model.
3. In the skill's **Interaction Model**, add the custom intent `PlayAudio`.
  LaunchRequest is a request type (not an intent) and is handled automatically by EchoWeave.
4. In **Endpoint**, set the default region endpoint to your public EchoWeave URL: `https://your-domain.com/alexa`
5. Build your interaction model.
6. Copy your **Skill ID** (format: `amzn1.ask.skill.xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx`).
7. Return to the EchoWeave Setup page and fill in the **Manual Alexa Skill Setup (Phase 1)** form with:
   - Your Skill ID (copied above)
   - Optionally: Your public HTTPS endpoint URL
   - Checkbox if you manually configured AWS credentials
8. Save. Your skill is now linked and should appear as ✅ **Alexa Skill Created** in the checklist.

## Important Notes & Constraints

*   **Experimental Status:** EchoWeave is currently an experimental standalone bridge backend.
*   **Public HTTPS / SSL Required:** Alexa AudioPlayer skills **require** a valid, public HTTPS endpoint secured by a trusted SSL certificate. You *must* have a reverse proxy (like Nginx Proxy Manager or Cloudflare Tunnels) exposing the add-on's port to the public internet. Local IP addresses, unencrypted HTTP, and internal hostnames (like `.local`) will be rejected by Alexa and by EchoWeave's internal security validations.

## Edge Mode Configuration

Set these options in Home Assistant add-on configuration when mode is edge:

- mode: edge
- worker_base_url: https://your-worker-domain
- tunnel_base_url: https://your-home-origin-domain
- edge_shared_secret: shared HMAC secret used by Worker to fetch local stream origin
- connector_id
- connector_secret
- tenant_id
- home_id
- alexa_source_queue_id
- ma_base_url
- ma_token

## Reverse Proxy and Tunnel

In edge mode, Alexa webhook should target Worker endpoint /v1/alexa.
The add-on tunnel URL should be reachable by Worker for /edge/stream requests.

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

### Current

- **ASK Automation:** ASK CLI wrappers are stubbed. Full AWS credential management and ASK deployment automation is **Phase 2+**. 
- **Manual Alexa Skill Setup Expected:** In Phase 1, users must manually:
  1. Create an Alexa skill in the [Amazon Developer Console](https://developer.amazon.com/alexa/console/ask).
  2. Configure the skill's HTTPS endpoint to point to the public EchoWeave URL (e.g., `https://your-domain.com/alexa`).
  3. Enter the skill ID into EchoWeave's Setup form under **Manual Alexa Skill Setup (Phase 1)**.
- Worker Alexa signature verification is only partially implemented today (header and cert URL checks plus timestamp checks). Full cryptographic verification remains pending.
- **Session store is JSON-file-backed** (not a database) — suitable for single-device testing but not recommended for production multi-user deployments.
- **No multi-user / multi-device concurrent testing yet** — limited isolation between simultaneous Alexa device sessions.

### Why Setup Shows "ASK Setup" as Optional

In Phase 1, the Setup wizard labels the "ASK Setup" step as optional because automated ASK credential management is not yet available. This step only completes if you explicitly mark it via the manual setup form. Users *can* skip this step entirely — the core skill functionality (playback control, Music Assistant integration) works once you link your manually-created skill ID.

## License

Apache-2.0
