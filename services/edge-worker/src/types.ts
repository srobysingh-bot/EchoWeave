export interface Env {
  ECHOWEAVE_DB: D1Database;
  HOME_SESSION: DurableObjectNamespace;
  STREAM_TOKEN_SIGNING_SECRET: string;
  CONNECTOR_BOOTSTRAP_SECRET?: string;
  ADMIN_API_KEY?: string;
  BUILD_ID?: string;
  RATE_LIMIT_ALEXA_PER_MINUTE?: string;
  RATE_LIMIT_ADMIN_PER_MINUTE?: string;
  RATE_LIMIT_CONNECTOR_REGISTER_PER_MINUTE?: string;
  EDGE_ORIGIN_SHARED_SECRET: string;
  ALEXA_SIGNATURE_ENFORCE?: string;
  STREAM_TOKEN_TTL_SECONDS?: string;
}

export interface AlexaRequestEnvelope {
  version?: string;
  session?: {
    user?: {
      userId?: string;
    };
  };
  context?: {
    System?: {
      user?: {
        userId?: string;
      };
      device?: {
        deviceId?: string;
      };
    };
  };
  request?: {
    type?: string;
    timestamp?: string;
    intent?: {
      name?: string;
      slots?: Record<string, unknown>;
    };
  };
}

export interface HomeMapping {
  tenant_id: string;
  home_id: string;
  origin_base_url: string;
  alexa_source_queue_id: string | null;
}

export interface ConnectorRegistrationPayload {
  connector_id: string;
  connector_secret: string;
  tenant_id: string;
  home_id: string;
  origin_base_url?: string;
  alexa_source_queue_id?: string;
  capabilities?: Record<string, unknown>;
}

export interface PreparePlayRequest {
  queue_id?: string;
  intent_name?: string;
  query?: string;
}

export interface PreparedPlayContext {
  queue_id: string;
  queue_item_id: string;
  title: string;
  subtitle?: string;
  image_url?: string;
  origin_stream_path: string;
  content_type?: string;
}

export interface StreamTokenClaims {
  token_id: string;
  tenant_id: string;
  home_id: string;
  playback_session_id: string;
  queue_id: string;
  queue_item_id: string;
  origin_stream_path: string;
  exp: number;
}

export interface HomeSessionDurableObject {
  fetch(request: Request): Promise<Response>;
}
