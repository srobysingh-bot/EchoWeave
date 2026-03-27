# Release Checklist

Use this checklist before calling an edge deployment production-ready.

## Required Infrastructure

- [ ] D1 migrations applied from services/edge-worker/schema.sql
- [ ] Worker deployed with correct bindings
- [ ] Durable Object migration applied
- [ ] BUILD_ID configured

## Required Secrets

- [ ] STREAM_TOKEN_SIGNING_SECRET set
- [ ] EDGE_ORIGIN_SHARED_SECRET set
- [ ] ADMIN_API_KEY set and enforced
- [ ] Optional CONNECTOR_BOOTSTRAP_SECRET set if used

## Provisioning and Linking

- [ ] Home provisioned via POST /v1/admin/homes
- [ ] User provisioned via POST /v1/admin/users
- [ ] Alexa account linked via POST /v1/admin/alexa-accounts/link
- [ ] Connector bootstrap executed and credentials delivered

## Runtime Readiness

- [ ] /healthz returns d1_reachable=true and build_id present
- [ ] Admin home status endpoint returns provisioning_complete=true
- [ ] Connector online=true in admin status
- [ ] Add-on status page shows Worker Provisioning as ready
- [ ] Add-on status page shows Alexa Account Linking as linked

## Stream and Playback Validation

- [ ] /v1/stream/:token succeeds with valid token
- [ ] Invalid/expired stream token rejected as expected
- [ ] Alexa PlayIntent returns AudioPlayer.Play
- [ ] Worker proxy reaches add-on origin stream path

## Smoke Tests

- [ ] scripts/provision_home_example.sh executed successfully
- [ ] scripts/smoke_worker.sh executed successfully

## Known Limitations Acknowledged

- [ ] Full Alexa trust-chain and revocation checks are still partial
- [ ] Tunnel/origin availability assumptions documented
- [ ] Manual Alexa console setup still required
- [ ] No full end-user automated account-linking UX yet
