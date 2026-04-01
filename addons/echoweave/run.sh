#!/usr/bin/with-contenv bashio
set -euo pipefail

CONFIG_PATH="/data/options.json"

if [ ! -f "$CONFIG_PATH" ]; then
    bashio::log.error "Options file not found at $CONFIG_PATH"
    exit 1
fi

export ECHOWEAVE_MODE="$(bashio::config 'mode')"
export ECHOWEAVE_BACKEND_URL="$(bashio::config 'backend_url')"
export ECHOWEAVE_WORKER_BASE_URL="$(bashio::config 'worker_base_url')"
export ECHOWEAVE_TUNNEL_BASE_URL="$(bashio::config 'tunnel_base_url')"
export ECHOWEAVE_EDGE_SHARED_SECRET="$(bashio::config 'edge_shared_secret')"
export ECHOWEAVE_CONNECTOR_ID="$(bashio::config 'connector_id')"
export ECHOWEAVE_CONNECTOR_SECRET="$(bashio::config 'connector_secret')"
export ECHOWEAVE_TENANT_ID="$(bashio::config 'tenant_id')"
export ECHOWEAVE_HOME_ID="$(bashio::config 'home_id')"
export ECHOWEAVE_ALEXA_SOURCE_QUEUE_ID="$(bashio::config 'alexa_source_queue_id')"
export ECHOWEAVE_MA_BASE_URL="$(bashio::config 'ma_base_url')"
export ECHOWEAVE_MA_TOKEN="$(bashio::config 'ma_token')"
export ECHOWEAVE_PUBLIC_BASE_URL="$(bashio::config 'public_base_url')"
export ECHOWEAVE_STREAM_BASE_URL="$(bashio::config 'stream_base_url')"
export ECHOWEAVE_UI_USERNAME="$(bashio::config 'ui_username')"
export ECHOWEAVE_UI_PASSWORD="$(bashio::config 'ui_password')"
export ECHOWEAVE_AWS_DEFAULT_REGION="$(bashio::config 'aws_default_region')"
export ECHOWEAVE_LOCALE="$(bashio::config 'locale')"
export ECHOWEAVE_LOG_LEVEL="$(bashio::config 'log_level')"
export ECHOWEAVE_DEBUG="$(bashio::config 'debug')"
export ECHOWEAVE_ALLOW_INSECURE_LOCAL_TEST="$(bashio::config 'allow_insecure_local_test')"
export ECHOWEAVE_ALLOW_INSECURE="$ECHOWEAVE_ALLOW_INSECURE_LOCAL_TEST"
export ECHOWEAVE_DATA_DIR="/data"

if [ -z "$ECHOWEAVE_MA_BASE_URL" ]; then
    bashio::log.warning "Music Assistant base URL is not configured yet."
fi

mkdir -p /data/sessions
mkdir -p /data/diagnostics
mkdir -p /data/ask
mkdir -p /data/logs

bashio::log.info "--------------------------------------------"
bashio::log.info " EchoWeave v0.3.6 starting"
bashio::log.info "--------------------------------------------"
bashio::log.info " Mode:          ${ECHOWEAVE_MODE:-legacy}"
bashio::log.info " Backend URL:   ${ECHOWEAVE_BACKEND_URL:-<not set>}"
bashio::log.info " Worker URL:    ${ECHOWEAVE_WORKER_BASE_URL:-<not set>}"
bashio::log.info " Tunnel URL:    ${ECHOWEAVE_TUNNEL_BASE_URL:-<not set>}"
bashio::log.info " Connector ID:  ${ECHOWEAVE_CONNECTOR_ID:-<not set>}"
bashio::log.info " Tenant/Home:   ${ECHOWEAVE_TENANT_ID:-<not set>}/${ECHOWEAVE_HOME_ID:-<not set>}"
bashio::log.info " Queue Source:  ${ECHOWEAVE_ALEXA_SOURCE_QUEUE_ID:-<not set>}"
bashio::log.info " MA URL:        ${ECHOWEAVE_MA_BASE_URL:-<not set>}"
bashio::log.info " Public URL:    ${ECHOWEAVE_PUBLIC_BASE_URL:-<not set>}"
bashio::log.info " Stream URL:    ${ECHOWEAVE_STREAM_BASE_URL:-<not set>}"
bashio::log.info " Locale:        ${ECHOWEAVE_LOCALE}"
bashio::log.info " Log level:     ${ECHOWEAVE_LOG_LEVEL}"
bashio::log.info " Debug:         ${ECHOWEAVE_DEBUG}"
bashio::log.info " MA Token:      ****"
bashio::log.info "--------------------------------------------"

exec python -m uvicorn app.main:app \
    --host 0.0.0.0 \
    --port 5000 \
    --log-level "${ECHOWEAVE_LOG_LEVEL:-info}" \
    --no-access-log
