import { beforeEach, describe, expect, test } from "vitest";

import { HomeSession } from "../src/durable_objects/HomeSession";

class FakeSocket {
  listeners: Record<string, Array<(event: any) => void>> = {};
  onSend?: (raw: string, socket: FakeSocket) => void;

  accept(): void {
    return;
  }

  addEventListener(type: string, cb: (event: any) => void): void {
    this.listeners[type] = this.listeners[type] || [];
    this.listeners[type].push(cb);
  }

  send(raw: string): void {
    if (this.onSend) this.onSend(raw, this);
  }

  close(): void {
    this.emit("close", {});
  }

  emit(type: string, event: any): void {
    for (const cb of this.listeners[type] || []) cb(event);
  }
}

let lastServerSocket: FakeSocket | null = null;

class FakeWebSocketPair {
  0: FakeSocket;
  1: FakeSocket;

  constructor() {
    this[0] = new FakeSocket();
    this[1] = new FakeSocket();
    lastServerSocket = this[1];
  }
}

beforeEach(() => {
  lastServerSocket = null;
  (globalThis as any).WebSocketPair = FakeWebSocketPair;
});

function createSession(): HomeSession {
  const state = {
    storage: {
      async put(): Promise<void> {
        return;
      },
    },
  };
  return new HomeSession(state as any);
}

describe("HomeSession durable object", () => {
  test("connector websocket attach and command relay success", async () => {
    const session = createSession();

    const attachResp = await session.fetch(
      new Request("https://home-session/attach?connector_id=conn1&tenant_id=t1&home_id=h1", {
        method: "GET",
        headers: { Upgrade: "websocket" },
      }),
    );
    expect([101, 200]).toContain(attachResp.status);

    expect(lastServerSocket).not.toBeNull();
    const server = lastServerSocket as FakeSocket;
    server.onSend = (raw, socket) => {
      const parsed = JSON.parse(raw) as { request_id: string };
      socket.emit("message", {
        data: JSON.stringify({ type: "response", request_id: parsed.request_id, ok: true, payload: { ok: true } }),
      });
    };

    const commandResp = await session.fetch(
      new Request("https://home-session/command", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ command_type: "prepare_play", payload: { queue_id: "q1" }, timeout_ms: 2000 }),
      }),
    );

    expect(commandResp.status).toBe(200);
    const payload = (await commandResp.json()) as { ok: boolean };
    expect(payload.ok).toBe(true);
  });

  test("command relay timeout handling", async () => {
    const session = createSession();

    await session.fetch(
      new Request("https://home-session/attach?connector_id=conn1&tenant_id=t1&home_id=h1", {
        method: "GET",
        headers: { Upgrade: "websocket" },
      }),
    );

    const commandResp = await session.fetch(
      new Request("https://home-session/command", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ command_type: "prepare_play", payload: {}, timeout_ms: 1000 }),
      }),
    );

    expect(commandResp.status).toBe(502);
    const payload = (await commandResp.json()) as { error: string };
    expect(payload.error).toContain("connector-timeout");
  });

  test("disconnect handling marks connector offline", async () => {
    const session = createSession();

    await session.fetch(
      new Request("https://home-session/attach?connector_id=conn1&tenant_id=t1&home_id=h1", {
        method: "GET",
        headers: { Upgrade: "websocket" },
      }),
    );

    (lastServerSocket as FakeSocket).close();

    const statusResp = await session.fetch(new Request("https://home-session/status", { method: "GET" }));
    const status = (await statusResp.json()) as { online: boolean };
    expect(status.online).toBe(false);

    const commandResp = await session.fetch(
      new Request("https://home-session/command", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ command_type: "prepare_play", payload: {}, timeout_ms: 1000 }),
      }),
    );
    expect(commandResp.status).toBe(503);
  });
});
