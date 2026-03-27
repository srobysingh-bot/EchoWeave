PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS homes (
  id TEXT PRIMARY KEY,
  tenant_id TEXT NOT NULL,
  name TEXT,
  origin_base_url TEXT NOT NULL,
  edge_shared_secret_ref TEXT,
  connector_id TEXT,
  alexa_source_queue_id TEXT,
  is_active INTEGER NOT NULL DEFAULT 1,
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  UNIQUE(tenant_id, id)
);

CREATE TABLE IF NOT EXISTS users (
  id TEXT PRIMARY KEY,
  tenant_id TEXT NOT NULL,
  email TEXT,
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS alexa_accounts (
  alexa_user_id TEXT PRIMARY KEY,
  user_id TEXT NOT NULL,
  tenant_id TEXT NOT NULL,
  home_id TEXT NOT NULL,
  access_scope TEXT,
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  FOREIGN KEY(user_id) REFERENCES users(id),
  FOREIGN KEY(home_id) REFERENCES homes(id)
);

CREATE TABLE IF NOT EXISTS home_connectors (
  connector_id TEXT PRIMARY KEY,
  tenant_id TEXT NOT NULL,
  home_id TEXT NOT NULL,
  connector_secret_hash TEXT NOT NULL,
  capabilities_json TEXT,
  registration_status TEXT NOT NULL DEFAULT 'registered',
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  FOREIGN KEY(home_id) REFERENCES homes(id)
);

CREATE TABLE IF NOT EXISTS connector_sessions (
  id TEXT PRIMARY KEY,
  connector_id TEXT NOT NULL,
  tenant_id TEXT NOT NULL,
  home_id TEXT NOT NULL,
  connected_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  disconnected_at TEXT,
  status TEXT NOT NULL DEFAULT 'online',
  FOREIGN KEY(connector_id) REFERENCES home_connectors(connector_id),
  FOREIGN KEY(home_id) REFERENCES homes(id)
);

CREATE TABLE IF NOT EXISTS connector_bootstraps (
  id TEXT PRIMARY KEY,
  tenant_id TEXT NOT NULL,
  home_id TEXT NOT NULL,
  connector_id TEXT NOT NULL,
  connector_secret_hash TEXT NOT NULL,
  expires_at TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'active',
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  FOREIGN KEY(home_id) REFERENCES homes(id),
  FOREIGN KEY(connector_id) REFERENCES home_connectors(connector_id)
);

CREATE TABLE IF NOT EXISTS playback_sessions (
  id TEXT PRIMARY KEY,
  tenant_id TEXT NOT NULL,
  home_id TEXT NOT NULL,
  alexa_user_id TEXT NOT NULL,
  queue_id TEXT,
  queue_item_id TEXT,
  stream_token_id TEXT,
  state TEXT NOT NULL DEFAULT 'prepared',
  metadata_json TEXT,
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  FOREIGN KEY(home_id) REFERENCES homes(id),
  FOREIGN KEY(alexa_user_id) REFERENCES alexa_accounts(alexa_user_id)
);

CREATE TABLE IF NOT EXISTS stream_tokens (
  id TEXT PRIMARY KEY,
  tenant_id TEXT NOT NULL,
  home_id TEXT NOT NULL,
  playback_session_id TEXT,
  token_signature TEXT NOT NULL,
  expires_at TEXT NOT NULL,
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  FOREIGN KEY(playback_session_id) REFERENCES playback_sessions(id),
  FOREIGN KEY(home_id) REFERENCES homes(id)
);

CREATE INDEX IF NOT EXISTS idx_alexa_accounts_home_id ON alexa_accounts(home_id);
CREATE INDEX IF NOT EXISTS idx_home_connectors_home_id ON home_connectors(home_id);
CREATE INDEX IF NOT EXISTS idx_connector_sessions_connector_id ON connector_sessions(connector_id);
CREATE INDEX IF NOT EXISTS idx_connector_bootstraps_home_id ON connector_bootstraps(home_id);
CREATE INDEX IF NOT EXISTS idx_playback_sessions_home_id ON playback_sessions(home_id);
CREATE INDEX IF NOT EXISTS idx_stream_tokens_home_id ON stream_tokens(home_id);
