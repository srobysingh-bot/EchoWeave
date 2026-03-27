# EchoWeave Operator Runbook

## Scope

This runbook covers release-candidate operations for edge mode deployment and support.

## A. Prerequisites

- Cloudflare account with Worker, D1, and Durable Object support.
- Home Assistant with EchoWeave add-on installed.
- Public domain/tunnel for add-on edge stream origin.
- Alexa Skill in Amazon Developer Console.

Required Worker bindings and config:

- D1 binding: ECHOWEAVE_DB
- Durable Object binding: HOME_SESSION
- Compatibility date aligned with repository wrangler config

Required Worker secrets:

- STREAM_TOKEN_SIGNING_SECRET
- EDGE_ORIGIN_SHARED_SECRET
- ADMIN_API_KEY
- Optional: CONNECTOR_BOOTSTRAP_SECRET

Required migration:

- Apply current schema file before deployment: services/edge-worker/schema.sql

Required endpoint setup:

- Alexa skill endpoint for edge mode must be Worker /v1/alexa
- Add-on must run in mode=edge with worker_base_url, tunnel_base_url, connector identity, tenant/home, and MA settings

## B. Deployment Sequence

1. Apply D1 schema/migrations.
2. Configure Wrangler with D1 and Durable Object bindings.
3. Set Worker secrets.
4. Deploy Worker.
5. Provision home/user/alexa mapping using admin APIs.
6. Configure Home Assistant add-on edge settings.
7. Verify tunnel/origin reachability from Worker to add-on /edge/stream path.
8. Configure Alexa skill endpoint to Worker /v1/alexa.
9. Run smoke tests.

## C. Smoke Test Procedure

1. Worker health:
   - GET /healthz
   - Confirm build_id present and d1_reachable=true
2. Admin home status:
   - GET /v1/admin/homes/:tenant_id/:home_id/status with bearer auth
   - Confirm readiness.provisioning_complete
3. Connector session:
   - Confirm connector.online=true and last_websocket_activity_at is recent
4. Add-on status page:
   - Confirm Worker Provisioning and Alexa Account Linking cards
   - Confirm edge mode diagnostics show worker_base_url and tenant/home
5. Stream token path:
   - GET /v1/stream/:token with valid unexpired token
   - Confirm 200/206
6. Alexa happy path:
   - Trigger PlayIntent from linked account
   - Confirm AudioPlayer.Play response and stream proxy fetch

Use scripts:

- scripts/provision_home_example.sh
- scripts/smoke_worker.sh

## D. Troubleshooting Matrix

- Connector offline:
  - Symptom: admin status connector.online=false
  - Check add-on mode=edge, connector credentials, websocket auth, and Worker logs
- Home not provisioned:
  - Symptom: /v1/admin/homes/:tenant/:home/status returns not found
  - Action: provision home via POST /v1/admin/homes
- Alexa account not linked:
  - Symptom: /v1/alexa returns account-not-linked speech
  - Action: POST /v1/admin/alexa-accounts/link with correct tenant/home/user
- Invalid Worker secret:
  - Symptom: stream proxy 401/502 or admin 401/403/503
  - Action: verify ADMIN_API_KEY and edge secret parity
- Stream token expired:
  - Symptom: /v1/stream/:token returns 401
  - Action: replay Alexa request to issue fresh token
- Worker cannot reach origin:
  - Symptom: stream proxy failed origin_stream_error
  - Action: verify tunnel_base_url, DNS/tunnel health, and add-on route
- MA queue/item resolution failure:
  - Symptom: prepare_play fails or 502 from Alexa flow
  - Action: validate MA token, queue binding, and MA server reachability
- Alexa signature validation failure:
  - Symptom: /v1/alexa returns 401 request signature failed
  - Action: verify Amazon headers and timestamp freshness; check Worker logs for alexa_request_rejected reason

## E. Secret Rotation

Connector secret rotation (recommended no/low downtime if coordinated):

1. Call POST /v1/admin/connectors/bootstrap to issue new connector_secret.
2. Update add-on connector_secret.
3. Restart add-on connector session.
4. Validate connector online status.

Worker secret rotation order:

1. Rotate ADMIN_API_KEY and update operator tooling first.
2. Rotate STREAM_TOKEN_SIGNING_SECRET during maintenance window (invalidates outstanding stream tokens).
3. Rotate EDGE_ORIGIN_SHARED_SECRET in coordinated step with add-on edge_shared_secret update.
4. Re-run smoke tests.

Expected impact:

- STREAM_TOKEN_SIGNING_SECRET rotation can break in-flight stream URLs until refreshed.
- EDGE_ORIGIN_SHARED_SECRET mismatch causes stream proxy auth failures until both sides match.

## Security Status Honesty

Current Alexa verification includes:

- signature cert URL validation
- cert fetch and parsing
- SAN/time checks
- timestamp freshness checks
- RSA signature verification against raw body

Still partial:

- full trust chain verification and revocation handling are not complete yet.
