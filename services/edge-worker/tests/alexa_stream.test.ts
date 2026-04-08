import { describe, expect, test, vi, beforeEach, afterEach } from "vitest";

import { handleAlexaWebhook } from "../src/alexa";
import { issueSignedStreamToken } from "../src/security";
import { handleStreamRequest } from "../src/stream";
import { StreamTokenClaims } from "../src/types";
import { createEnv, MockD1Database } from "./mock_env";

const baseAlexaEnvelope = {
  version: "1.0",
  request: {
    type: "IntentRequest",
    timestamp: new Date().toISOString(),
    intent: { name: "PlayIntent" },
  },
  session: {
    user: {
      userId: "alexa-user-a",
    },
  },
};

function setupLinkedHome(env: ReturnType<typeof createEnv>) {
  const db = env.ECHOWEAVE_DB as unknown as MockD1Database;
  db.homes.set("home-a", {
    id: "home-a",
    tenant_id: "tenant-a",
    name: "Home A",
    origin_base_url: "https://origin.example.com",
    connector_id: "conn-a",
    alexa_source_queue_id: "queue-a",
    is_active: 1,
  });
  db.alexaAccounts.set("alexa-user-a", {
    alexa_user_id: "alexa-user-a",
    user_id: "user-a",
    tenant_id: "tenant-a",
    home_id: "home-a",
  });
  return db;
}

function createValidStreamClaims(overrides?: Partial<StreamTokenClaims>): StreamTokenClaims {
  return {
    token_id: "t1",
    tenant_id: "tenant-a",
    home_id: "home-a",
    playback_session_id: "p1",
    queue_id: "q1",
    queue_item_id: "i1",
    origin_stream_path: "/edge/stream/q1/i1",
    exp: Math.floor(Date.now() / 1000) + 300,
    ...overrides,
  };
}

describe("alexa routing and stream token checks", () => {
  test("/v1/alexa returns not-linked error when mapping is missing", async () => {
    const env = createEnv({ ALEXA_SIGNATURE_ENFORCE: "false" });
    const req = new Request("https://worker/v1/alexa", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify(baseAlexaEnvelope),
    });

    const resp = await handleAlexaWebhook(req, env);
    expect(resp.status).toBe(200);
    const body = (await resp.json()) as { response: { outputSpeech: { text: string } } };
    expect(body.response.outputSpeech.text.toLowerCase()).toContain("not linked");
  });

  test("/v1/alexa resolves linked home and returns AudioPlayer.Play", async () => {
    const env = createEnv({ ALEXA_SIGNATURE_ENFORCE: "false" });
    setupLinkedHome(env);

    const req = new Request("https://worker/v1/alexa", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify(baseAlexaEnvelope),
    });

    const resp = await handleAlexaWebhook(req, env);
    expect(resp.status).toBe(200);

    const body = (await resp.json()) as {
      response: {
        directives: Array<{ type: string; audioItem: { stream: { url: string } } }>;
      };
    };
    expect(body.response.directives[0].type).toBe("AudioPlayer.Play");
    expect(body.response.directives[0].audioItem.stream.url).toContain("/v1/stream/");
  });

  test("/v1/stream/:token rejects invalid and expired tokens", async () => {
    const env = createEnv();

    const invalidResp = await handleStreamRequest(new Request("https://worker/v1/stream/bad"), env, "bad");
    expect(invalidResp.status).toBe(401);

    const expiredClaims = createValidStreamClaims({
      exp: Math.floor(Date.now() / 1000) - 30,
    });
    const expiredToken = await issueSignedStreamToken(expiredClaims, env.STREAM_TOKEN_SIGNING_SECRET);
    const expiredResp = await handleStreamRequest(new Request("https://worker/v1/stream/expired"), env, expiredToken);
    expect(expiredResp.status).toBe(401);
  });
});

describe("LaunchRequest session handling", () => {
  test("launch response keeps session open for follow-up utterances", async () => {
    const env = createEnv({ ALEXA_SIGNATURE_ENFORCE: "false" });
    const launchEnvelope = {
      version: "1.0",
      request: {
        type: "LaunchRequest",
        timestamp: new Date().toISOString(),
      },
      session: {
        user: { userId: "alexa-user-a" },
      },
    };

    const req = new Request("https://worker/v1/alexa", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify(launchEnvelope),
    });

    const resp = await handleAlexaWebhook(req, env);
    expect(resp.status).toBe(200);

    const body = (await resp.json()) as {
      response: {
        shouldEndSession: boolean;
        outputSpeech: { text: string };
        reprompt?: { outputSpeech: { text: string } };
      };
    };
    expect(body.response.shouldEndSession).toBe(false);
    expect(body.response.outputSpeech.text).toBeTruthy();
    expect(body.response.reprompt).toBeTruthy();
  });

  test("play intent after launch stays in-skill and returns AudioPlayer.Play", async () => {
    const env = createEnv({ ALEXA_SIGNATURE_ENFORCE: "false" });
    setupLinkedHome(env);

    // Simulate multi-turn: launch first, then play intent
    const playEnvelope = {
      version: "1.0",
      request: {
        type: "IntentRequest",
        timestamp: new Date().toISOString(),
        intent: {
          name: "PlayIntent",
          slots: { query: { value: "arijit singh" } },
        },
      },
      session: {
        user: { userId: "alexa-user-a" },
      },
    };

    const req = new Request("https://worker/v1/alexa", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify(playEnvelope),
    });

    const resp = await handleAlexaWebhook(req, env);
    expect(resp.status).toBe(200);

    const body = (await resp.json()) as {
      response: {
        directives: Array<{ type: string; audioItem: { stream: { url: string } } }>;
        shouldEndSession: boolean;
      };
    };
    expect(body.response.directives).toBeDefined();
    expect(body.response.directives[0].type).toBe("AudioPlayer.Play");
    expect(body.response.shouldEndSession).toBe(true);
  });
});

describe("edge stream target selection and signing", () => {
  let originalFetch: typeof globalThis.fetch;
  let fetchCalls: Array<{ url: string; headers: Record<string, string> }>;

  beforeEach(() => {
    originalFetch = globalThis.fetch;
    fetchCalls = [];
    globalThis.fetch = (async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = typeof input === "string" ? input : input instanceof URL ? input.toString() : input.url;
      const headers: Record<string, string> = {};
      if (init?.headers) {
        const h = init.headers as Record<string, string>;
        for (const [k, v] of Object.entries(h)) {
          headers[k.toLowerCase()] = v;
        }
      }
      fetchCalls.push({ url, headers });
      return new Response("fake-audio-bytes", {
        status: 200,
        headers: {
          "content-type": "audio/mpeg",
          "content-length": "16",
          "accept-ranges": "bytes",
        },
      });
    }) as typeof globalThis.fetch;
  });

  afterEach(() => {
    globalThis.fetch = originalFetch;
  });

  async function issueValidTokenAndRecord(env: ReturnType<typeof createEnv>) {
    const db = env.ECHOWEAVE_DB as unknown as MockD1Database;
    setupLinkedHome(env);

    const claims = createValidStreamClaims();
    const token = await issueSignedStreamToken(claims, env.STREAM_TOKEN_SIGNING_SECRET);
    const sig = token.split(".")[1] ?? "";

    db.streamTokens.set("t1", {
      id: "t1",
      tenant_id: "tenant-a",
      home_id: "home-a",
      playback_session_id: "p1",
      token_signature: sig,
      expires_at: new Date(Date.now() + 300_000).toISOString(),
    });

    return token;
  }

  test("stream request uses origin_stream_path, NOT source_url", async () => {
    const env = createEnv();
    const token = await issueValidTokenAndRecord(env);

    const req = new Request("https://worker/v1/stream/test");
    const resp = await handleStreamRequest(req, env, token);

    expect(resp.status).toBe(200);
    expect(fetchCalls.length).toBe(1);

    const call = fetchCalls[0];
    // Must use origin_base_url + origin_stream_path, NOT the private MA source_url
    expect(call.url).toContain("origin.example.com");
    expect(call.url).toContain("/edge/stream/q1/i1");
    // Must NOT use the private MA URL
    expect(call.url).not.toContain("192.168.1.100");
    expect(call.url).not.toContain("8095");
  });

  test("stream request includes edge signing headers", async () => {
    const env = createEnv();
    const token = await issueValidTokenAndRecord(env);

    const req = new Request("https://worker/v1/stream/test");
    const resp = await handleStreamRequest(req, env, token);

    expect(resp.status).toBe(200);
    expect(fetchCalls.length).toBe(1);

    const headers = fetchCalls[0].headers;
    // Must include the edge auth headers expected by stream_router.py
    expect(headers["x-edge-timestamp"]).toBeTruthy();
    expect(headers["x-edge-signature"]).toBeTruthy();
    // Timestamp should be a valid unix epoch
    expect(Number(headers["x-edge-timestamp"])).toBeGreaterThan(1000000000);
    // Should also include diagnostic headers
    expect(headers["x-edge-token-id"]).toBe("t1");
    expect(headers["x-request-id"]).toBeTruthy();
  });

  test("Range header is forwarded to upstream", async () => {
    const env = createEnv();
    const token = await issueValidTokenAndRecord(env);

    const req = new Request("https://worker/v1/stream/test", {
      headers: { range: "bytes=0-1024" },
    });
    const resp = await handleStreamRequest(req, env, token);

    expect(resp.status).toBe(200);
    expect(fetchCalls.length).toBe(1);
    expect(fetchCalls[0].headers["range"]).toBe("bytes=0-1024");
  });

  test("missing origin_stream_path returns 502 with clear error", async () => {
    const env = createEnv();
    const db = env.ECHOWEAVE_DB as unknown as MockD1Database;
    setupLinkedHome(env);

    // Issue token with empty origin_stream_path
    const claims = createValidStreamClaims({ origin_stream_path: "" });
    const token = await issueSignedStreamToken(claims, env.STREAM_TOKEN_SIGNING_SECRET);
    const sig = token.split(".")[1] ?? "";

    db.streamTokens.set("t1", {
      id: "t1",
      tenant_id: "tenant-a",
      home_id: "home-a",
      playback_session_id: "p1",
      token_signature: sig,
      expires_at: new Date(Date.now() + 300_000).toISOString(),
    });

    // Override DO to return no origin_stream_path
    const customEnv = createEnv({
      ALEXA_SIGNATURE_ENFORCE: "false",
      HOME_SESSION: {
        idFromName: () => "id",
        get: () => ({
          fetch: async (_req: Request | string, init?: RequestInit) => {
            const url = typeof _req === "string" ? _req : _req.url;
            if (url.endsWith("/command")) {
              return new Response(
                JSON.stringify({ source_url: "http://192.168.1.100/media/123" }),
                { status: 200, headers: { "content-type": "application/json" } },
              );
            }
            return new Response("{}", { status: 404 });
          },
        }),
      } as any,
    });
    // Copy DB state
    (customEnv.ECHOWEAVE_DB as unknown as MockD1Database).homes = db.homes;
    (customEnv.ECHOWEAVE_DB as unknown as MockD1Database).streamTokens = db.streamTokens;

    const req = new Request("https://worker/v1/stream/test");
    const resp = await handleStreamRequest(req, customEnv, token);

    expect(resp.status).toBe(502);
    const text = await resp.text();
    expect(text).toContain("origin stream path");
  });

  test("happy-path returns audio bytes with correct headers", async () => {
    const env = createEnv();
    const token = await issueValidTokenAndRecord(env);

    const req = new Request("https://worker/v1/stream/test");
    const resp = await handleStreamRequest(req, env, token);

    expect(resp.status).toBe(200);
    expect(resp.headers.get("content-type")).toBe("audio/mpeg");
    expect(resp.headers.get("accept-ranges")).toBe("bytes");
    const body = await resp.text();
    expect(body).toBe("fake-audio-bytes");
  });
});
