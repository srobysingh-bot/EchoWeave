# EchoWeave Home Assistant Add-ons

This repository hosts the EchoWeave Home Assistant add-on and edge control plane for Alexa to Music Assistant playback.

## Production Target

- Primary production ingress: services/edge-worker
- Durable session coordinator: services/edge-worker/src/durable_objects/HomeSession.ts
- Home Assistant local runtime: addons/echoweave
- Prototype or dev-only legacy control plane: services/cloud-backend

The add-on is now designed to run as a local connector and secure stream origin in edge mode, while public Alexa ingress is handled by the Worker.

## Runtime Modes

- legacy: Add-on hosts direct Alexa webhook and stream path for historical flow.
- connector: Add-on uses legacy cloud-backend polling connector flow.
- edge: Add-on opens outbound websocket to edge worker and serves signed local edge stream route. In this mode, add-on does not expose public Alexa webhook as primary architecture.

## How to Install

You can add this repository to your Home Assistant instance by following these steps:

1. Navigate to your Home Assistant instance.
2. Go to **Settings** > **Add-ons**.
3. Click on the **Add-on Store** button in the bottom right corner.
4. Click the three-dot menu (**⋮**) in the top right corner and select **Repositories**.
5. Paste the GitHub URL of this repository (`https://github.com/srobysingh-bot/EchoWeave`) into the "Add repository" field and click **Add**.
6. Close the dialog. The new repository should appear at the bottom of the Add-on Store list.
7. Click the **EchoWeave** add-on and select **Install**.

## Important Notes & Constraints

- Experimental status: Edge architecture is active but still under migration hardening.
- Public HTTPS and SSL required for Alexa skill endpoint in production.
- Worker Alexa signature verification now performs request-body signature checks using Alexa cert material, timestamp freshness enforcement, and cert URL/SAN/time validation.
- Production onboarding is API-driven; manual SQL seeding is no longer required for home/user/link provisioning.
- Admin APIs are now bearer-protected via `ADMIN_API_KEY` and should never be exposed without a gateway policy.
- Worker supports per-route rate limits via `RATE_LIMIT_ALEXA_PER_MINUTE`, `RATE_LIMIT_ADMIN_PER_MINUTE`, and `RATE_LIMIT_CONNECTOR_REGISTER_PER_MINUTE`.

## Edge Mode Required Fields

Configure these add-on options for edge mode:

- mode = edge
- worker_base_url
- tunnel_base_url
- edge_shared_secret
- connector_id
- connector_secret
- tenant_id
- home_id
- alexa_source_queue_id
- ma_base_url
- ma_token

## Worker Onboarding APIs

The Worker now exposes deterministic onboarding and linking endpoints:

- POST /v1/admin/homes
- POST /v1/admin/users
- POST /v1/admin/alexa-accounts/link
- POST /v1/admin/connectors/bootstrap
- GET /v1/admin/homes/:tenant_id/:home_id/status

These endpoints back the edge-mode provisioning lifecycle and eliminate default-home fallback behavior.

For exact provisioning and linking commands, see docs/WORKER_ONBOARDING.md.

For operator procedures and incident handling, see docs/OPERATOR_RUNBOOK.md.
For pre-release sign-off, use docs/RELEASE_CHECKLIST.md.
