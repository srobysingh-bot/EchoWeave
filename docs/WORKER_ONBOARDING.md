# EchoWeave Worker Onboarding and Linking

This document covers deterministic provisioning for edge mode without manual SQL edits.

## Prerequisites

- Worker deployed and reachable at WORKER_BASE_URL.
- D1 binding applied.
- ADMIN_API_KEY set in Worker secrets for production admin API protection.
- Add-on configured with matching tenant_id and home_id.

## Environment Variables

```bash
export WORKER_BASE_URL="https://your-worker-domain"
export ADMIN_API_KEY="replace-with-admin-key"
export TENANT_ID="tenant-a"
export HOME_ID="home-a"
export USER_ID="user-a"
export ALEXA_USER_ID="amzn1.account.ABC123"
```

## 1) Create or Update Home

```bash
curl -sS -X POST "$WORKER_BASE_URL/v1/admin/homes" \
  -H "authorization: Bearer $ADMIN_API_KEY" \
  -H "content-type: application/json" \
  -d "{\"tenant_id\":\"$TENANT_ID\",\"home_id\":\"$HOME_ID\",\"name\":\"Primary Home\",\"origin_base_url\":\"https://your-origin-domain\",\"alexa_source_queue_id\":\"queue-a\"}"
```

## 2) Create or Update User

```bash
curl -sS -X POST "$WORKER_BASE_URL/v1/admin/users" \
  -H "authorization: Bearer $ADMIN_API_KEY" \
  -H "content-type: application/json" \
  -d "{\"user_id\":\"$USER_ID\",\"tenant_id\":\"$TENANT_ID\",\"email\":\"owner@example.com\"}"
```

## 3) Link Alexa Account to Tenant and Home

```bash
curl -sS -X POST "$WORKER_BASE_URL/v1/admin/alexa-accounts/link" \
  -H "authorization: Bearer $ADMIN_API_KEY" \
  -H "content-type: application/json" \
  -d "{\"alexa_user_id\":\"$ALEXA_USER_ID\",\"user_id\":\"$USER_ID\",\"tenant_id\":\"$TENANT_ID\",\"home_id\":\"$HOME_ID\"}"
```

## 4) Bootstrap Connector Credentials

```bash
curl -sS -X POST "$WORKER_BASE_URL/v1/admin/connectors/bootstrap" \
  -H "authorization: Bearer $ADMIN_API_KEY" \
  -H "content-type: application/json" \
  -d "{\"tenant_id\":\"$TENANT_ID\",\"home_id\":\"$HOME_ID\",\"connector_id\":\"conn-home-a\",\"ttl_seconds\":3600}"
```

Save connector_id and connector_secret into add-on edge configuration.

## 5) Check Provisioning Status

```bash
curl -sS "$WORKER_BASE_URL/v1/admin/homes/$TENANT_ID/$HOME_ID/status" \
  -H "authorization: Bearer $ADMIN_API_KEY"
```

Expected key fields:

- result.connector.registration_status
- result.connector.online
- result.alexa_account_linked
- result.origin_base_url
- result.queue_binding

## Conflict and Idempotency Behavior

- Home create/update is idempotent for same tenant/home pair.
- User create/update is idempotent for same tenant/user pair.
- Alexa mapping link is idempotent for same alexa_user_id to same target.
- Cross-tenant remap attempts are rejected with conflict responses.
- No default-home fallback routing is used.

## D1 Rollout Order

Apply schema updates before rolling Worker code that depends on new tables.

1. Deploy schema containing connector_bootstraps table.
2. Verify admin routes for homes, users, and linking return success.
3. Bootstrap connector credentials.
4. Roll add-on edge config.
5. Validate home status endpoint shows provisioned and linked.

## Production Hardening Checklist

- Enforce ADMIN_API_KEY in all non-local environments.
- Restrict admin API access at edge firewall level.
- Rotate connector bootstrap secrets frequently.
- Rotate EDGE_ORIGIN_SHARED_SECRET and STREAM_TOKEN_SIGNING_SECRET on schedule.
- Complete full X.509 chain trust validation and revocation strategy for Alexa certs.
- Add structured security event logging and alerting for signature failures.
- Add rate limiting for /v1/alexa and admin endpoints.
