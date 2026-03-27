#!/usr/bin/env bash
set -euo pipefail

: "${WORKER_BASE_URL:?Set WORKER_BASE_URL}"
: "${ADMIN_API_KEY:?Set ADMIN_API_KEY}"
: "${TENANT_ID:?Set TENANT_ID}"
: "${HOME_ID:?Set HOME_ID}"
: "${USER_ID:?Set USER_ID}"
: "${ALEXA_USER_ID:?Set ALEXA_USER_ID}"
: "${ORIGIN_BASE_URL:?Set ORIGIN_BASE_URL}"
: "${QUEUE_ID:?Set QUEUE_ID}"

AUTH=( -H "authorization: Bearer ${ADMIN_API_KEY}" -H "content-type: application/json" )

echo "Create/update home"
curl -fsS -X POST "${WORKER_BASE_URL}/v1/admin/homes" "${AUTH[@]}" \
  -d "{\"tenant_id\":\"${TENANT_ID}\",\"home_id\":\"${HOME_ID}\",\"name\":\"Primary Home\",\"origin_base_url\":\"${ORIGIN_BASE_URL}\",\"alexa_source_queue_id\":\"${QUEUE_ID}\"}"

echo "Create/update user"
curl -fsS -X POST "${WORKER_BASE_URL}/v1/admin/users" "${AUTH[@]}" \
  -d "{\"user_id\":\"${USER_ID}\",\"tenant_id\":\"${TENANT_ID}\",\"email\":\"owner@example.com\"}"

echo "Link alexa account"
curl -fsS -X POST "${WORKER_BASE_URL}/v1/admin/alexa-accounts/link" "${AUTH[@]}" \
  -d "{\"alexa_user_id\":\"${ALEXA_USER_ID}\",\"user_id\":\"${USER_ID}\",\"tenant_id\":\"${TENANT_ID}\",\"home_id\":\"${HOME_ID}\"}"

echo "Bootstrap connector"
curl -fsS -X POST "${WORKER_BASE_URL}/v1/admin/connectors/bootstrap" "${AUTH[@]}" \
  -d "{\"tenant_id\":\"${TENANT_ID}\",\"home_id\":\"${HOME_ID}\",\"connector_id\":\"conn-${HOME_ID}\",\"ttl_seconds\":3600}"

echo "Fetch status"
curl -fsS "${WORKER_BASE_URL}/v1/admin/homes/${TENANT_ID}/${HOME_ID}/status" -H "authorization: Bearer ${ADMIN_API_KEY}"
