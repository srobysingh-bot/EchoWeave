interface PendingRequest {
  resolve: (payload: unknown) => void;
  reject: (reason: Error) => void;
  timeout: number;
}

type CloudflareWebSocket = WebSocket & { accept(): void };

declare const WebSocketPair: {
  new (): { 0: CloudflareWebSocket; 1: CloudflareWebSocket };
};

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

export class HomeSession {
  private state: any;
  private connectorSocket: CloudflareWebSocket | null;
  private connectorMeta: { connector_id: string; tenant_id: string; home_id: string } | null;
  private pending: Map<string, PendingRequest>;
  private lastMetadata: Record<string, unknown>;

  constructor(state: any) {
    this.state = state;
    this.connectorSocket = null;
    this.connectorMeta = null;
    this.pending = new Map();
    this.lastMetadata = {};
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

    await this.state.storage.put("last_attach", {
      connector_id: connectorId,
      tenant_id: tenantId,
      home_id: homeId,
      attached_at: new Date().toISOString(),
    });

    return new Response(null, { status: 101, webSocket: client } as ResponseInit & { webSocket: WebSocket });
  }

  private async relayCommand(request: Request): Promise<Response> {
    if (!this.isConnectorOnline() || !this.connectorSocket) {
      return this.json({ error: "connector-offline" }, 503);
    }

    const body = (await request.json()) as {
      command_type: string;
      payload: Record<string, unknown>;
      timeout_ms?: number;
    };
    if (!body.command_type) return this.json({ error: "missing-command-type" }, 400);

    const requestId = crypto.randomUUID();
    const timeoutMs = Math.max(1000, Math.min(Number(body.timeout_ms ?? 8000), 20000));
    const envelope: ConnectorCommandEnvelope = {
      type: "command",
      request_id: requestId,
      command_type: body.command_type,
      payload: body.payload ?? {},
    };

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
      return this.json(payload, 200);
    } catch (error) {
      const message = error instanceof Error ? error.message : "connector-command-failed";
      return this.json({ error: message }, 502);
    }
  }

  async fetch(request: Request): Promise<Response> {
    const path = new URL(request.url).pathname;

    if (path === "/attach") return this.attachConnector(request);
    if (path === "/command" && request.method === "POST") return this.relayCommand(request);
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
