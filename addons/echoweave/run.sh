#!/usr/bin/with-contenv bashio
set -euo pipefail

CONFIG_PATH="/data/options.json"

if [ ! -f "$CONFIG_PATH" ]; then
    bashio::log.error "Options file not found at $CONFIG_PATH"
    exit 1
fi

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
export ECHOWEAVE_ALLOW_INSECURE="$(bashio::config 'allow_insecure_local_test')"
export ECHOWEAVE_DATA_DIR="/data"

if [ -z "$ECHOWEAVE_MA_BASE_URL" ]; then
    bashio::log.warning "Music Assistant base URL is not configured yet."
fi

mkdir -p /data/sessions
mkdir -p /data/diagnostics
mkdir -p /data/ask
mkdir -p /data/logs

bashio::log.info "--------------------------------------------"
bashio::log.info " EchoWeave v0.1.5 starting"
bashio::log.info "--------------------------------------------"
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
