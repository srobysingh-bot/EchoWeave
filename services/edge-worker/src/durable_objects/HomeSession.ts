interface PendingRequest {
  resolve: (payload: unknown) => void;
  reject: (reason: Error) => void;
  timeout: number;
}

type CloudflareWebSocket = WebSocket & { accept(): void };

declare const WebSocketPair: {
  new (): { 0: CloudflareWebSocket; 1: CloudflareWebSocket };
};

function createWebSocketUpgradeResponse(client: CloudflareWebSocket): Response {
  try {
    return new Response(null, { status: 101, webSocket: client } as ResponseInit & { webSocket: WebSocket });
  } catch {
    // Node/undici test runtimes can reject status 101, while Worker runtime supports it.
    return new Response(null, { status: 200, headers: { "x-websocket-upgrade": "mock" } });
  }
}

interface ConnectorCommandEnvelope {
  type: "command";
  request_id: string;
  command_type: string;
  payload: Record<string, unknown>;
}

interface ConnectorResponseEnvelope {
  type: "response";
  request_id: string;
  ok: boolean;
  payload?: unknown;
  error?: string | { code?: string; message?: string; details?: Record<string, unknown> };
}

interface PlaybackStartState {
  playback_session_id: string;
  token_id: string;
  request_id: string;
  created_at_ms: number;
  created_at_iso: string;
  fetched_at_ms?: number;
  fetched_at_iso?: string;
  fetch_request_id?: string;
  playback_started_at_ms?: number;
  playback_started_at_iso?: string;
  playback_started_request_id?: string;
  playback_failed_at_ms?: number;
  playback_failed_at_iso?: string;
  playback_failed_request_id?: string;
  playback_failed_error?: unknown;
  last_event_type?: string;
}

export class HomeSession {
  private state: any;
  private connectorSocket: CloudflareWebSocket | null;
  private connectorMeta: { connector_id: string; tenant_id: string; home_id: string } | null;
  private pending: Map<string, PendingRequest>;
  private lastMetadata: Record<string, unknown>;
  private playbackStarts: Map<string, PlaybackStartState>;

  constructor(state: any) {
    this.state = state;
    this.connectorSocket = null;
    this.connectorMeta = null;
    this.pending = new Map();
    this.lastMetadata = {};
    this.playbackStarts = new Map();
  }

  private json(data: unknown, status = 200): Response {
    return new Response(JSON.stringify(data), {
      status,
      headers: { "content-type": "application/json" },
    });
  }

  private isConnectorOnline(): boolean {
    return this.connectorSocket !== null && this.connectorMeta !== null;
  }

  private wireConnectorSocket(ws: CloudflareWebSocket): void {
    ws.accept();
    ws.addEventListener("message", (event) => {
      try {
        const parsed = JSON.parse(String(event.data)) as ConnectorResponseEnvelope | { type: "event"; event: string; payload: unknown };
        if (parsed.type === "response") {
          const pending = this.pending.get(parsed.request_id);
          if (!pending) return;
          console.info(
            JSON.stringify({
              event: "connector_response_received",
              request_id: parsed.request_id,
              ok: parsed.ok,
              connector_id: this.connectorMeta?.connector_id ?? "",
              error: parsed.ok ? undefined : parsed.error,
            }),
          );
          clearTimeout(pending.timeout);
          this.pending.delete(parsed.request_id);
          if (parsed.ok) {
            pending.resolve(parsed.payload ?? {});
          } else {
            const errorText =
              typeof parsed.error === "string"
                ? parsed.error
                : parsed.error?.message || parsed.error?.code || "connector-command-failed";
            pending.reject(new Error(errorText));
          }
          return;
        }

        if (parsed.type === "event") {
          this.lastMetadata = {
            event: parsed.event,
            payload: parsed.payload,
            received_at: new Date().toISOString(),
          };
        }
      } catch {
        // ignore malformed messages from connector, do not crash DO.
      }
    });

    const onClose = () => {
      this.connectorSocket = null;
      this.connectorMeta = null;
      for (const [requestId, pending] of this.pending.entries()) {
        clearTimeout(pending.timeout);
        pending.reject(new Error("connector-disconnected"));
        this.pending.delete(requestId);
      }
    };

    ws.addEventListener("close", onClose);
    ws.addEventListener("error", onClose);
  }

  private async attachConnector(request: Request): Promise<Response> {
    if (request.headers.get("Upgrade")?.toLowerCase() !== "websocket") {
      return this.json({ error: "upgrade-required" }, 426);
    }

    const url = new URL(request.url);
    const connectorId = url.searchParams.get("connector_id") ?? "";
    const tenantId = url.searchParams.get("tenant_id") ?? "";
    const homeId = url.searchParams.get("home_id") ?? "";
    if (!connectorId || !tenantId || !homeId) {
      return this.json({ error: "missing-connector-metadata" }, 400);
    }

    if (this.connectorSocket) {
      try {
        this.connectorSocket.close(1012, "replaced-by-new-connection");
      } catch {
        // no-op
      }
    }

    const pair = new WebSocketPair();
    const client = pair[0];
    const server = pair[1];
    this.connectorSocket = server;
    this.connectorMeta = {
      connector_id: connectorId,
      tenant_id: tenantId,
      home_id: homeId,
    };
    this.wireConnectorSocket(server);

    this.notifyConnectorAttached();

    await this.state.storage.put("last_attach", {
      connector_id: connectorId,
      tenant_id: tenantId,
      home_id: homeId,
      attached_at: new Date().toISOString(),
    });

    return createWebSocketUpgradeResponse(client);
  }

  private waitForConnectorResolve: ((value: void) => void) | null = null;

  private notifyConnectorAttached(): void {
    if (this.waitForConnectorResolve) {
      this.waitForConnectorResolve();
      this.waitForConnectorResolve = null;
    }
  }

  private async waitForConnector(timeoutMs: number): Promise<boolean> {
    if (this.isConnectorOnline()) return true;
    return new Promise<boolean>((resolve) => {
      const timer = setTimeout(() => {
        this.waitForConnectorResolve = null;
        resolve(this.isConnectorOnline());
      }, timeoutMs);
      this.waitForConnectorResolve = () => {
        clearTimeout(timer);
        resolve(true);
      };
    });
  }

  private async relayCommand(request: Request): Promise<Response> {
    if (!this.isConnectorOnline() || !this.connectorSocket) {
      console.info(JSON.stringify({ event: "connector_offline_grace_wait", wait_ms: 5000 }));
      const reconnected = await this.waitForConnector(5000);
      if (!reconnected || !this.connectorSocket) {
        return this.json({ error: "connector-offline" }, 503);
      }
      console.info(JSON.stringify({ event: "connector_reconnected_during_grace" }));
    }

    const parentRequestId = request.headers.get("x-request-id") ?? "";
    const body = (await request.json()) as {
      command_type: string;
      payload: Record<string, unknown>;
      timeout_ms?: number;
    };
    if (!body.command_type) return this.json({ error: "missing-command-type" }, 400);

    const requestId = crypto.randomUUID();
    const rawTimeout = Number(body.timeout_ms ?? 8000);
    const timeoutMs = Math.max(1000, Math.min(Number.isFinite(rawTimeout) ? rawTimeout : 8000, 20000));
    const envelope: ConnectorCommandEnvelope = {
      type: "command",
      request_id: requestId,
      command_type: body.command_type,
      payload: body.payload ?? {},
    };
    console.info(
      JSON.stringify({
        event: "connector_command_dispatch",
        request_id: requestId,
        parent_request_id: parentRequestId,
        command_type: body.command_type,
        timeout_ms: timeoutMs,
        connector_id: this.connectorMeta?.connector_id ?? "",
        payload: body.payload ?? {},
      }),
    );

    const commandPromise = new Promise<unknown>((resolve, reject) => {
      const timeout = setTimeout(() => {
        this.pending.delete(requestId);
        reject(new Error("connector-timeout"));
      }, timeoutMs) as unknown as number;
      this.pending.set(requestId, { resolve, reject, timeout });
    });

    this.connectorSocket.send(JSON.stringify(envelope));

    try {
      const payload = await commandPromise;
      console.info(
        JSON.stringify({
          event: "connector_command_result",
          request_id: requestId,
          parent_request_id: parentRequestId,
          ok: true,
          payload,
        }),
      );
      return this.json(payload, 200);
    } catch (error) {
      const message = error instanceof Error ? error.message : "connector-command-failed";
      console.warn(
        JSON.stringify({
          event: "connector_command_result",
          request_id: requestId,
          parent_request_id: parentRequestId,
          ok: false,
          error: message,
          command_type: body.command_type,
          connector_id: this.connectorMeta?.connector_id ?? "",
        }),
      );
      return this.json({ error: message }, 502);
    }
  }

  private playbackStartStorageKey(playbackSessionId: string): string {
    return `playback_start:${playbackSessionId}`;
  }

  private async getPlaybackStartState(playbackSessionId: string): Promise<PlaybackStartState | null> {
    const inMemory = this.playbackStarts.get(playbackSessionId);
    if (inMemory) return inMemory;

    const stored = (await this.state.storage.get(
      this.playbackStartStorageKey(playbackSessionId),
    )) as PlaybackStartState | null;
    if (stored) {
      this.playbackStarts.set(playbackSessionId, stored);
      return stored;
    }
    return null;
  }

  private async savePlaybackStartState(state: PlaybackStartState): Promise<void> {
    this.playbackStarts.set(state.playback_session_id, state);
    await this.state.storage.put(this.playbackStartStorageKey(state.playback_session_id), state);
  }

  private async handlePlaybackStart(request: Request): Promise<Response> {
    if (request.method !== "POST") return this.json({ error: "method-not-allowed" }, 405);

    const body = (await request.json()) as {
      action?: string;
      playback_session_id?: string;
      token_id?: string;
      request_id?: string;
      event_type?: string;
      error?: unknown;
    };

    const action = String(body.action ?? "").trim();
    const playbackSessionId = String(body.playback_session_id ?? "").trim();
    if (!action || !playbackSessionId) {
      return this.json({ error: "action and playback_session_id are required" }, 400);
    }

    if (action === "register") {
      const tokenId = String(body.token_id ?? "").trim();
      const requestId = String(body.request_id ?? "").trim();
      if (!tokenId) return this.json({ error: "token_id is required for register" }, 400);

      const now = Date.now();
      const state: PlaybackStartState = {
        playback_session_id: playbackSessionId,
        token_id: tokenId,
        request_id: requestId,
        created_at_ms: now,
        created_at_iso: new Date(now).toISOString(),
      };
      await this.savePlaybackStartState(state);

      return this.json({
        ok: true,
        action,
        playback_session_id: playbackSessionId,
        stream_fetch_started: false,
      });
    }

    if (action === "mark_fetched") {
      const requestId = String(body.request_id ?? "").trim();
      const existing = await this.getPlaybackStartState(playbackSessionId);
      if (!existing) {
        return this.json({
          ok: true,
          action,
          playback_session_id: playbackSessionId,
          stream_fetch_started: true,
          untracked_session: true,
        });
      }

      if (!existing.fetched_at_ms) {
        const now = Date.now();
        existing.fetched_at_ms = now;
        existing.fetched_at_iso = new Date(now).toISOString();
        existing.fetch_request_id = requestId;
        await this.savePlaybackStartState(existing);
      }

      return this.json({
        ok: true,
        action,
        playback_session_id: playbackSessionId,
        stream_fetch_started: true,
        fetched_at_iso: existing.fetched_at_iso,
      });
    }

    if (action === "status") {
      const existing = await this.getPlaybackStartState(playbackSessionId);
      if (!existing) {
        return this.json({
          ok: true,
          action,
          playback_session_id: playbackSessionId,
          known_session: false,
          stream_fetch_started: false,
        });
      }

      return this.json({
        ok: true,
        action,
        playback_session_id: playbackSessionId,
        play_request_id: existing.request_id,
        known_session: true,
        stream_fetch_started: !!existing.fetched_at_ms,
        playback_started: !!existing.playback_started_at_ms,
        playback_failed: !!existing.playback_failed_at_ms,
        created_at_iso: existing.created_at_iso,
        fetched_at_iso: existing.fetched_at_iso ?? null,
        playback_started_at_iso: existing.playback_started_at_iso ?? null,
        playback_failed_at_iso: existing.playback_failed_at_iso ?? null,
        playback_failed_error: existing.playback_failed_error ?? null,
        last_event_type: existing.last_event_type ?? null,
        age_ms: Date.now() - existing.created_at_ms,
        token_id: existing.token_id,
      });
    }

    if (action === "mark_playback_event") {
      const eventType = String(body.event_type ?? "").trim();
      const requestId = String(body.request_id ?? "").trim();
      const existing = await this.getPlaybackStartState(playbackSessionId);
      if (!existing) {
        return this.json({
          ok: true,
          action,
          playback_session_id: playbackSessionId,
          known_session: false,
          ignored: true,
        });
      }

      const now = Date.now();
      if (eventType === "AudioPlayer.PlaybackStarted") {
        existing.playback_started_at_ms = existing.playback_started_at_ms ?? now;
        existing.playback_started_at_iso = existing.playback_started_at_iso ?? new Date(now).toISOString();
        existing.playback_started_request_id = requestId;
        existing.last_event_type = eventType;
      } else if (eventType === "AudioPlayer.PlaybackFailed") {
        existing.playback_failed_at_ms = existing.playback_failed_at_ms ?? now;
        existing.playback_failed_at_iso = existing.playback_failed_at_iso ?? new Date(now).toISOString();
        existing.playback_failed_request_id = requestId;
        existing.playback_failed_error = body.error ?? null;
        existing.last_event_type = eventType;
      }

      await this.savePlaybackStartState(existing);

      return this.json({
        ok: true,
        action,
        playback_session_id: playbackSessionId,
        play_request_id: existing.request_id,
        known_session: true,
        stream_fetch_started: !!existing.fetched_at_ms,
        playback_started: !!existing.playback_started_at_ms,
        playback_failed: !!existing.playback_failed_at_ms,
        last_event_type: existing.last_event_type ?? null,
      });
    }

    return this.json({ error: "unsupported-action" }, 400);
  }

  async fetch(request: Request): Promise<Response> {
    const path = new URL(request.url).pathname;

    if (path === "/attach") return this.attachConnector(request);
    if (path === "/command" && request.method === "POST") return this.relayCommand(request);
    if (path === "/playback-start") return this.handlePlaybackStart(request);
    if (path === "/status") {
      return this.json({
        online: this.isConnectorOnline(),
        connector: this.connectorMeta,
        last_metadata: this.lastMetadata,
      });
    }

    return this.json({ error: "not-found" }, 404);
  }
}
