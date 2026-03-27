#!/usr/bin/env bash
set -euo pipefail

: "${WORKER_BASE_URL:?Set WORKER_BASE_URL}"
: "${TENANT_ID:?Set TENANT_ID}"
: "${HOME_ID:?Set HOME_ID}"
: "${STREAM_TOKEN:?Set STREAM_TOKEN for stream smoke check}"

AUTH_HEADER=()
if [[ -n "${ADMIN_API_KEY:-}" ]]; then
  AUTH_HEADER=( -H "authorization: Bearer ${ADMIN_API_KEY}" )
fi

echo "[1/5] Worker health"
curl -fsS "${WORKER_BASE_URL}/healthz" | sed 's/.*/  &/'

echo "[2/5] Home status"
curl -fsS "${WORKER_BASE_URL}/v1/admin/homes/${TENANT_ID}/${HOME_ID}/status" "${AUTH_HEADER[@]}" | sed 's/.*/  &/'

echo "[3/5] Alexa endpoint liveness (expected 401/400 without signed request)"
STATUS=$(curl -s -o /dev/null -w '%{http_code}' -X POST "${WORKER_BASE_URL}/v1/alexa" -H 'content-type: application/json' -d '{}')
echo "  status=${STATUS}"

echo "[4/5] Stream token endpoint"
STREAM_STATUS=$(curl -s -o /dev/null -w '%{http_code}' "${WORKER_BASE_URL}/v1/stream/${STREAM_TOKEN}")
echo "  status=${STREAM_STATUS}"

echo "[5/5] Connector registration endpoint smoke (method check)"
REG_STATUS=$(curl -s -o /dev/null -w '%{http_code}' "${WORKER_BASE_URL}/v1/connectors/register")
echo "  status=${REG_STATUS}"

echo "Smoke checks completed."
