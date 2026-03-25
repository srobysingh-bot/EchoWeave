"""Central constants, route prefixes, defaults, and file paths."""

# ---------------------------------------------------------------------------
# Application metadata
# ---------------------------------------------------------------------------
APP_NAME = "EchoWeave"
APP_VERSION = "0.1.9"
APP_DESCRIPTION = "Alexa bridge backend for Music Assistant"

# ---------------------------------------------------------------------------
# Route prefixes
# ---------------------------------------------------------------------------
ROUTE_HEALTH = "/health"
ROUTE_STATUS = "/status"
ROUTE_SETUP = "/setup"
ROUTE_LOGS = "/logs"
ROUTE_CONFIG = "/config"
ROUTE_ALEXA = "/alexa"

# ---------------------------------------------------------------------------
# Default values
# ---------------------------------------------------------------------------
DEFAULT_PORT = 5000
DEFAULT_LOG_LEVEL = "info"
DEFAULT_LOCALE = "en-US"
DEFAULT_AWS_REGION = "us-east-1"
DEFAULT_UI_USERNAME = "admin"
DEFAULT_DATA_DIR = "/data"

# ---------------------------------------------------------------------------
# Persistent storage file names (under DATA_DIR)
# ---------------------------------------------------------------------------
FILE_CONFIG = "config.json"
FILE_SESSIONS = "sessions"
FILE_DIAGNOSTICS = "diagnostics"
FILE_ASK = "ask"
FILE_LOGS = "logs"
FILE_SKILL_META = "skill_metadata.json"
FILE_HEALTH_CACHE = "health_cache.json"

# ---------------------------------------------------------------------------
# Health check subsystem keys
# ---------------------------------------------------------------------------
HEALTH_KEY_SERVICE = "service"
HEALTH_KEY_MA_REACHABLE = "ma_reachable"
HEALTH_KEY_MA_AUTH = "ma_auth_valid"
HEALTH_KEY_PUBLIC_URL = "public_url_reachable"
HEALTH_KEY_STREAM_URL = "stream_url_valid"
HEALTH_KEY_ASK_CONFIGURED = "ask_configured"
HEALTH_KEY_SKILL_EXISTS = "skill_exists"

# ---------------------------------------------------------------------------
# Secret field names (for redaction)
# ---------------------------------------------------------------------------
SECRET_FIELDS = frozenset({
    "ma_token",
    "ui_password",
    "password",
    "token",
    "secret",
    "authorization",
    "cookie",
    "x-api-key",
    "aws_secret_access_key",
})

# ---------------------------------------------------------------------------
# Alexa AudioPlayer constants
# ---------------------------------------------------------------------------
ALEXA_PLAY_BEHAVIOR_REPLACE_ALL = "REPLACE_ALL"
ALEXA_PLAY_BEHAVIOR_ENQUEUE = "ENQUEUE"
ALEXA_CLEAR_BEHAVIOR_ALL = "CLEAR_ALL"
ALEXA_CLEAR_BEHAVIOR_ENQUEUED = "CLEAR_ENQUEUED"
