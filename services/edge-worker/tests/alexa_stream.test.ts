import { describe, expect, test } from "vitest";

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

    const expiredClaims: StreamTokenClaims = {
      token_id: "t1",
      tenant_id: "tenant-a",
      home_id: "home-a",
      playback_session_id: "p1",
      queue_id: "queue-a",
      queue_item_id: "item-a",
      origin_stream_path: "/edge/stream/queue-a/item-a",
      exp: Math.floor(Date.now() / 1000) - 30,
    };
    const expiredToken = await issueSignedStreamToken(expiredClaims, env.STREAM_TOKEN_SIGNING_SECRET);
    const expiredResp = await handleStreamRequest(new Request("https://worker/v1/stream/expired"), env, expiredToken);
    expect(expiredResp.status).toBe(401);
  });
});
