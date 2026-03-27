# EchoWeave Edge Architecture Migration

## Summary

This migration moves EchoWeave from prototype mixed ingress to an edge-first architecture:

- Alexa public ingress now targets Cloudflare Worker (`services/edge-worker`).
- Home Assistant add-on now supports `mode=edge` as a first-class runtime mode.
- Add-on keeps local MA integration and exposes signed local stream origin endpoint (`/edge/stream/{queue_id}/{queue_item_id}`).
- Add-on keeps an outbound persistent WebSocket connection to the Worker in edge mode.
- Music Assistant is treated as media/queue authority, not Echo playback controller.

Milestone target in this document: Alexa request -> Worker -> Durable Object -> add-on prepare_play -> MA resolution -> Worker stream token -> Worker proxy stream.

## What Changed

### New Worker Project

Created `services/edge-worker` with:

- `wrangler.jsonc`, `package.json`, `tsconfig.json`
- `schema.sql` D1 schema
- route handlers and security modules
- Durable Object home session coordinator

Implemented endpoints:

- `POST /v1/alexa`
- `GET /v1/stream/:token`
- `POST /v1/connectors/register`
- `GET /v1/connectors/ws`

Implemented home Durable Object responsibilities:

- connector websocket attach/detach
- request/response command relay with correlation IDs
- online/offline state surface via `/status`
- in-memory last metadata snapshots

### Add-on Edge Mode

Added edge config fields and persistence:

- `mode = legacy | connector | edge`
- `worker_base_url`
- `tunnel_base_url`
- `edge_shared_secret`
- `connector_id`
- `connector_secret`
- `tenant_id`
- `home_id`
- `alexa_source_queue_id`

In `mode=edge`:

- direct Alexa router is not mounted
- connector polling heartbeat loop is not used for playback command path
- add-on registers connector with Worker and opens persistent outbound websocket
- add-on serves secure local stream route for Worker-origin fetches
- add-on sends connector hello/auth metadata envelopes over websocket
- add-on command dispatch returns resolver-style payloads for Alexa-as-player

### MA Client Refactor

Extended MA client to support resolver semantics:

- `resolve_play_request(...)`
- `get_current_playable_item(...)`
- `get_next_playable_item(...)`
- `build_stream_context(...)`
- `get_item_metadata(...)`
- `get_queue_state(...)`

These methods provide metadata and stream source resolution for Alexa-as-player mode.

## Deprecated/Legacy Paths

- Direct add-on Alexa ingress (`/alexa`) is legacy-only and disabled in `mode=edge`.
- Connector polling/heartbeat command loop remains only for legacy connector mode and is not the edge playback path.
- `services/cloud-backend` is now prototype/dev-only and no longer the target production ingress.

## Worker Contract Alignment

Current contract used by add-on edge websocket client and Worker Durable Object:

- DO -> add-on command envelope: type=command, request_id, command_type, payload
- add-on -> DO command response envelope: type=response, request_id, ok, payload or structured error
- add-on -> DO event envelope: connector_hello and connector_auth for connector state metadata

Connector registration payload now supports:

- connector_id
- connector_secret
- tenant_id
- home_id
- origin_base_url
- alexa_source_queue_id
- capabilities

## Running Worker Locally

1. `cd services/edge-worker`
2. `npm install`
3. Create D1 DB and bind in `wrangler.jsonc`
4. Apply schema:
   - `npm run db:migrate`
5. Set required Worker secrets:
   - `STREAM_TOKEN_SIGNING_SECRET`
   - `EDGE_ORIGIN_SHARED_SECRET`
   - optional `CONNECTOR_BOOTSTRAP_SECRET`
6. Start local Worker:
   - `npm run dev`

## Running Add-on in Edge Mode

Set add-on options (or env) for:

- `mode: edge`
- `worker_base_url`
- `tunnel_base_url`
- `edge_shared_secret`
- `connector_id`
- `connector_secret`
- `tenant_id`
- `home_id`
- optional `alexa_source_queue_id`
- MA fields: `ma_base_url`, `ma_token`

Then restart add-on.

Expected behavior:

- add-on registers connector at Worker `/v1/connectors/register`
- add-on opens websocket to Worker `/v1/connectors/ws`
- add-on handles `prepare_play` commands and returns resolved MA playable context
- Worker returns Alexa `AudioPlayer.Play` with signed stream URL
- Worker stream endpoint proxies from add-on `/edge/stream/...`

## TODO (External Setup)

- TODO: Configure Cloudflare account resources (Worker route, Durable Object migration, D1 binding IDs).
- TODO: Provision production secret management for per-home edge shared secret material.
- TODO: Complete Alexa cert chain and body signature cryptographic verification inside Worker runtime.
- TODO: Configure Alexa Skill endpoint and account-linking records in D1 (`alexa_accounts`, `users`, `homes`).
- TODO: Configure Cloudflare Tunnel/origin identity for each home and update `homes.origin_base_url`.

## Initial E2E Happy Path Covered

Implemented first path for “Alexa, ask EchoWeave to play”:

1. Worker receives Alexa request.
2. Worker validates envelope + timestamp + required signature headers and cert URL shape.
3. Worker resolves Alexa user to tenant/home via D1.
4. Worker sends `prepare_play` to home Durable Object.
5. Add-on resolves playable context from MA.
6. Worker issues signed stream token.
7. Worker returns Alexa `AudioPlayer.Play` directive.
8. Alexa fetches Worker stream URL.
9. Worker validates token and proxies audio from add-on secure stream origin.

## Known Partial Items

- Full Alexa certificate chain and body signature verification in Worker is still incomplete.
- Production tunnel deployment and per-home secret lifecycle are external infrastructure tasks.
