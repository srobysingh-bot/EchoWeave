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
2. **Edge Mode Settings:** Configure worker_base_url, tunnel_base_url, connector identity, tenant/home IDs, and edge shared secret.
3. **Provision and Link:** Ensure Worker provisioning APIs have home/user/alexa mapping configured.
4. Click **Validate and Save**. The setup wizard and status page show edge readiness and linking state.

### Edge Mode Alexa Skill Endpoint

Completing the setup checklist in Phase 1 requires manually creating and configuring an Alexa skill:

1. Go to the [Amazon Developer Console](https://developer.amazon.com/alexa/console/ask).
2. Create a new **Alexa Skills Kit (ASK)** skill with a custom model.
3. In the skill's **Interaction Model**, add the custom intent `PlayAudio`.
  LaunchRequest is a request type (not an intent) and is handled automatically by EchoWeave.
4. In **Endpoint**, set the default region endpoint to your Worker URL: `https://your-worker-domain/v1/alexa`
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

## Provisioning and Linking

In edge mode, onboarding should be done through Worker admin endpoints:

- `POST /v1/admin/homes`
- `POST /v1/admin/users`
- `POST /v1/admin/alexa-accounts/link`
- `POST /v1/admin/connectors/bootstrap`
- `GET /v1/admin/homes/:tenant_id/:home_id/status`

The add-on status page calls Worker home status in edge mode and shows whether the system is still waiting for Alexa account linking.

For exact API examples, see docs/WORKER_ONBOARDING.md.

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
  2. In edge mode, configure the skill HTTPS endpoint to point to Worker `/v1/alexa` (e.g., `https://your-worker-domain/v1/alexa`).
  3. Enter the skill ID into EchoWeave's Setup form under **Manual Alexa Skill Setup (Phase 1)**.
- Worker Alexa signature verification performs cert URL validation, cert fetch/parsing, SAN/time checks, request timestamp checks, and RSA-SHA1 verification against the exact request body.
- **Session store is JSON-file-backed** (not a database) — suitable for single-device testing but not recommended for production multi-user deployments.
- **No multi-user / multi-device concurrent testing yet** — limited isolation between simultaneous Alexa device sessions.
- **Alexa UI-start requires active skill context:** A Music Assistant UI click alone cannot use prototype-skill `AudioPlayer.Play` delivery. Without active Alexa request context (`inbound_request_id` or recent `/alexa/intents` probe), `/ma/push-url` returns `ui_play_requires_active_alexa_skill_session` and does not attempt worker handoff/prototype response playback.

### Why Setup Shows "ASK Setup" as Optional

In Phase 1, the Setup wizard labels the "ASK Setup" step as optional because automated ASK credential management is not yet available. This step only completes if you explicitly mark it via the manual setup form. Users *can* skip this step entirely — the core skill functionality (playback control, Music Assistant integration) works once you link your manually-created skill ID.

## License

Apache-2.0
