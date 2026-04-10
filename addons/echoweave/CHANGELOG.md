# Changelog

All notable changes to EchoWeave will be documented in this file.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/).
 
## [0.3.24] - 2026-04-10
 
### Added
 
- Enhanced `ma/push-url` logging to parse player and track IDs for UI playback interception research.
- Added foundational logic for 'Magic UI Fix' to bridge local/public stream URL gap.
 
## [0.3.23] - 2026-04-09
 
### Fixed
 
- Hardened queue item retrieval with null checks to prevent crashes when a queue is not found.
- Resolved `AttributeError` in `get_current_queue_item` when source queue resolution fails.
 
## [0.3.22] - 2026-04-09
 
### Fixed
 
- Added dummy `GET /alexa/intents` endpoint to resolve 404 errors when controlling playback from Music Assistant UI.
 
## [0.3.21] - 2026-04-09
 
### Fixed
 
- Added dummy `/ma/push-url` endpoint to resolve 404 errors during Music Assistant callback registration.
- Improved integration stability by acknowledging MA push notifications.
 
## [0.3.20] - 2026-04-09
 
### Fixed
 
- Refactor Music Assistant Command API payload to use nested `args` and `message_id`.
- Resolve 500 Internal Server Errors caused by flat command payloads in MA 2.x.

## [0.3.19] - 2026-04-09

### Changed

- Migrate Music Assistant client to the POST-based Command API for full 2.x compatibility.
- Replace legacy REST GET endpoints for player queues with structured command payloads.
- Implement robust namespace fallbacks (`player_queues` vs `playerqueues`) for version-agnostic queue resolution.
- Bump add-on version to 0.3.19 to trigger fresh build/deployment.

## [0.3.18] - 2026-04-08

### Added

- Add `recent_alexa_users` tracking table to capture unlinked Alexa User IDs for easier debugging.
- Add `/v1/admin/debug-info` endpoint to expose captured Alexa User IDs, resolution state, and expected connector bootstrap secret.
- Bump add-on version to 0.3.18 and worker version to 0.1.4.

## [0.3.17] - 2026-04-08

### Fixed

- Route worker stream through signed add-on edge route instead of private MA URL.
- Update `stream.ts` to build upstream URL from `origin_base_url + origin_stream_path` with HMAC signing.
- Support `shouldEndSession` override in `buildAlexaSpeechResponse` and add stream token logs.
- Add structured `edge_stream_auth_failed` logging to add-on `stream_router.py`.
- Bump worker version to `0.1.3` and add-on markers to `0.3.17`.

## [0.3.16] - 2026-04-04

### Changed

- Add request correlation fields (`request_id`, `tenant_id`, `home_id`) from Worker to add-on `prepare_play` command payload for cross-layer tracing.
- Add MA player inventory diagnostics to capture selected `player_id`, online/availability state, active queue/source, and provider metadata during play resolution.
- Improve player selection fallback to prefer online/play-capable players before generic fallback.
- Expand playback start diagnostics to log play command targets, payloads, and MA provider error responses behind `play_start_failed`/`PlayerCommandFailed`.
- Align add-on/runtime version markers to `0.3.16`.

## [0.3.15] - 2026-04-04

### Changed

- Move playback handoff to Worker-only public edge path for stream delivery (`workers.dev` URL returned to Alexa).
- Add connector `resolve_stream` descriptor flow so Worker resolves source URL via private connector channel before proxying audio.
- Remove tunnel-origin dependency from edge playback registration path.
- Add/extend stream diagnostics for Worker stream proxy and add-on stream descriptor lookup stages.
- Align add-on/runtime version markers to `0.3.15`.

## [0.3.8] - 2026-04-01

### Changed

- Bump add-on/runtime markers to `0.3.8` to force another fresh Home Assistant add-on image pull/rebuild.
- Update deterministic runtime build fingerprint to `build_id=qr-20260401-cab5ea8`.
- Elevate key query diagnostics to warning level for live troubleshooting visibility: `prepare_play_start`, `ma_query_search`, `ma_artist_top_tracks`, and `ma_resolve_play_request` start phase.

## [0.3.7] - 2026-04-01

### Changed

- Bump add-on/runtime markers to `0.3.7` to force a fresh Home Assistant add-on image pull/rebuild.
- Add deterministic runtime build fingerprint `build_id=qr-20260401-8dc7588` for stale-container detection.
- Expose `build_id` and `query_resolution_rev` in `/healthz` and `/health` payloads for live-code verification.
- Emit startup log fields `build_id` and `query_resolution_rev` so operator logs can confirm the exact query resolver build.

## [0.3.6] - 2026-04-01

### Fixed

- Forward Alexa query slot text from Worker to connector `prepare_play` payload and add explicit Worker query logs (`alexa_intent_query`).
- Add query normalization for phrases like `songs by <artist>` and `music by <artist>`.
- Implement Music Assistant search fallback order for query-based play resolution: tracks, artists, albums, playlists.
- Add artist-resolution fallback to fetch and queue top tracks when artist matches are found.
- Add structured search observability logs (`prepare_play_start`, `ma_query_search`, `ma_artist_top_tracks`, `ma_resolve_play_request`).
- Align add-on and runtime version markers to `0.3.6`.

## [0.3.5] - 2026-04-01

### Fixed

- Enable `observability` natively in `services/edge-worker/wrangler.jsonc` for persistent Cloudflare Worker logging.
- Add `PlayAudio` intent mapping resolving to `AMAZON.SearchQuery` to reclaim media queries from global Alexa routing.
- Correctly assign `invocationName` to avoid prohibited Amazon wake words (`weave bridge`).
- Align add-on and runtime version markers to `0.3.5` and model version to `0.1.6`.

## [0.3.4] - 2026-03-30
### Fixed

- Reject stale numeric MA queue ids discovered from player state to avoid hard 404 queue lookups during PlayAudio preparation.
- Discard requested queue ids that return MA 404 and re-resolve against the active playable queue before failing.
- Apply stale queue-id sanitation consistently across play resolution and play command paths.
- Add regression tests for numeric queue-id rejection and 404 fallback behavior.
- Align add-on and runtime version markers to `0.3.4`.

## [0.3.3] - 2026-03-29

### Fixed

- Add edge `prepare_play` fallback: if a configured queue binding is stale/unplayable, retry with MA auto-discovered active queue.
- Align add-on and runtime version markers to `0.3.3`.

## [0.3.2] - 2026-03-29

### Fixed

- Relax add-on option schema for optional URL-like fields so updates do not fail when some mode-specific values are blank.
- Align add-on and runtime version markers to `0.3.2`.

## [0.3.1] - 2026-03-29

### Changed

- Align add-on and runtime version markers to `0.3.1`.

## [0.3.0] - 2026-03-27

### Added

- Add new `services/cloud-backend` FastAPI service skeleton with in-memory connector registry.
- Implement cloud endpoints: `GET /health`, `POST /v1/alexa` (LaunchRequest), `POST /v1/connectors/register`, and `POST /v1/connectors/{connector_id}/heartbeat`.
- Add cloud backend tests for health, LaunchRequest payload, connector registration, and heartbeat updates.
- Add connector-mode modules in add-on: `app/connector/client.py`, `app/connector/registration.py`, and `app/connector/heartbeat.py`.
- Add connector-mode tests for settings, setup page fields, status rendering, and registration client URL behavior.

### Changed

- Add mode-aware add-on config fields: `mode`, `backend_url`, `connector_id`, `connector_secret`, `tenant_id`, `home_id`.
- Start connector registration and periodic heartbeat on add-on startup when `mode=connector`.
- Update setup wizard to support connector-mode inputs and hide manual Alexa-skill setup in connector mode.
- Extend status diagnostics to include connector identity and heartbeat runtime state.
- Bump add-on/runtime markers to `0.3.0`.

## [0.2.4] - 2026-03-25

### Fixed

- Add explicit logging for every `/alexa` request and response, including `request.type`, intent name (if present), HTTP status, and final response JSON payload.
- Improve LaunchRequest instrumentation by logging entry into `_handle_launch`, the payload created by `build_response`, and full traceback visibility on exceptions.
- Return a strict minimal Alexa-safe LaunchRequest response with top-level `version`, top-level `sessionAttributes`, `outputSpeech`, `reprompt`, and `shouldEndSession=false`.
- Keep LaunchRequest response simple: no directives, no cards, no APL, and no Music Assistant dependency.
- Map custom intent `PlayAudio` to the same handler as `PlayIntent`, preserving backward compatibility for `PlayIntent`.
- Add explicit logging of selected intent handler to avoid ambiguous routing diagnostics.
- Clarify play-stub response text so Alexa fallback behavior cannot be misread as successful custom-skill playback.
- Add regression tests for LaunchRequest schema, PlayAudio routing, PlayIntent compatibility, and unknown-intent fallback.
- Clarify README wording that LaunchRequest is a request type (not an intent) and `PlayAudio` is the custom intent name.
- Align runtime and packaging markers to `0.2.4`.

## [0.2.3] - 2026-03-25

### Fixed

- Add explicit LaunchRequest response diagnostics in Alexa router logs, including `request.type`, full response payload, and returned HTTP status.
- Simplify LaunchRequest voice response to a minimal Alexa-safe payload:
	- `speech`: `Welcome to EchoWeave.`
	- `reprompt`: `Say play audio to begin.`
	- `shouldEndSession`: `false`
- Harden Alexa response envelopes by including top-level `sessionAttributes` (empty object by default) for schema consistency.
- Map custom intent name `PlayAudio` to the same handler as `PlayIntent` to support manually configured Alexa skills.
- Add integration tests for LaunchRequest response schema and for `IntentRequest` with intent name `PlayAudio`.
- Align runtime and packaging markers to `0.2.3`.

## [0.2.2] - 2026-03-25

### Fixed

- Address misleading UX in Setup wizard where Phase 1 stubs (ASK CLI, automated credential management) were presented as required blockers.
- Add manual Alexa skill setup mode enabling users to manually enter their skill ID from Amazon Developer Console without requiring unimplemented ASK automation.
- Rename "ASK Credentials Present" to "ASK Setup (Optional in Phase 1)" and remove false dependency on ASK CLI directory existence.
- Update SkillMetadata to track `manual_skill_configured` and `manual_ask_setup` flags for explicit manual setup mode state.
- Add new `/setup/save-skill` endpoint and UI form field for Phase 1 users to link pre-created Alexa skills.
- Document Phase 1 manual setup expectations and improve README Known Limitations to clarify ASK automation is Phase 2+.
- Add comprehensive tests for manual skill entry, ASK optional labeling, and setup checklist consistency.
- Align runtime and packaging markers to `0.2.2`.

## [0.2.1] - 2026-03-25

### Fixed

- Improve Alexa LaunchRequest reliability by returning an explicit welcome response with `outputSpeech`, `reprompt`, and `shouldEndSession=false`.
- Add request diagnostics logging for Alexa request type, intent name (when present), and LaunchRequest success/failure path visibility.
- Preserve existing PlayIntent behavior while adding regression tests for launch and intent handling.
- Align runtime and packaging markers to `0.2.1`.

## [0.2.0] - 2026-03-25

### Fixed

- Break recursive Public Endpoint health probing by introducing lightweight `GET /healthz` liveness and probing that path externally.
- Improve public endpoint unreachable diagnostics by including exception type and repr so failures are actionable.
- Refine stream endpoint semantics so base-root HTTP 404/405 is treated as reachable-but-base-empty (warning), not broken streaming.
- Preserve config source-of-truth precedence behavior and diagnostics source reporting from add-on options.
- Add tests for non-recursive public checks, `/healthz` behavior, trycloudflare public URL handling, richer error text, and stream-root warning semantics.
- Align runtime and packaging markers to `0.2.0`.

## [0.1.9] - 2026-03-25

### Fixed

- Make Home Assistant add-on options the highest-priority startup config source and prevent stale persisted values from overriding runtime checks.
- Add source-aware config resolution (`addon_options`, `environment`, `persisted_config`, `default`) and expose it on the Config page.
- Sync stale persisted config automatically to the effective runtime values on startup as a one-time repair path.
- Add startup logs for effective `ma_base_url`, `public_base_url`, `stream_base_url`, and `allow_insecure_local_test` with URL origin-only redaction.
- Ensure setup save updates persistence without breaking add-on option precedence on restart.
- Add status-page diagnostics for effective public/stream URLs and their sources.
- Align runtime and packaging markers to `0.1.9`.

## [0.1.8] - 2026-03-24

### Fixed

- Fix setup/config persistence roundtrip by wiring Config page to live ConfigService values and persisted updates.
- Display Music Assistant token presence as redacted indicator (`**** (set)`) instead of showing blank when configured.
- Switch MA validation to command-based `POST /api` requests and add command/url/status logging without exposing token values.
- Tighten stream/public endpoint health semantics to separate valid, reachable-but-invalid (for example HTTP 404), and unreachable states.
- Mark local HTTP public endpoints as local-test/non-production instead of Alexa-ready.
- Sync runtime and packaging version markers to `0.1.8`.
- Enable Home Assistant add-on `auto_update: true` and document repository refresh steps for faster version visibility in UI.

## [0.1.7] - 2026-03-24

### Fixed

- Replace ingress path mutation with pure ASGI scope normalization so malformed paths like `//` and `///setup` are rewritten before FastAPI route matching.
- Remove duplicated `/app/{addon_slug}` routes and keep only canonical app-local routes (`/`, `/setup`, `/status`, `/logs`, `/config`, `/health`, `/alexa`, `/debug/*`).
- Keep ingress awareness only for URL generation via `X-Ingress-Path`/`root_path`; routing is no longer reconstructed inside FastAPI.
- Add richer `/debug/routes` diagnostics including scope path/raw_path/root_path, request URL path, effective ingress base, and route table.
- Relax admin auth checks under ingress so Home Assistant ingress authentication is not blocked by add-on UI auth.
- Sync add-on and runtime versions to `0.1.7`.

## [0.1.6] - 2026-03-24

### Fixed

- Add ingress compatibility fallback for HA setups forwarding /app/<slug>/... without X-Ingress-Path.
- Keep debug endpoints available under both normal and /app/<slug> ingress-prefixed paths.
- Sync runtime and add-on metadata versions to 0.1.6.

## [0.1.5] - 2026-03-24

### Fixed

- Replace fake /app/{slug} route duplication with proper ingress base-path handling via X-Ingress-Path.
- Make redirects and UI links ingress-aware while keeping normal direct /setup, /status, /logs, /config routes.
- Add debug endpoints for route/base-path diagnostics.
- Sync add-on manifest, runtime constants, and startup banner to version 0.1.5.

## [0.1.4] - 2026-03-24

### Fixed

- Resolve ingress UI 404 diagnostics by exposing route debug endpoints and ingress-aware route coverage.
- Align runtime and startup versions to 0.1.4 across app constants, health/status responses, and add-on metadata.

## [0.1.3] - 2026-03-24

### Fixed

- Fix persistent s6-envdir startup crash by explicitly running Home Assistant init via ENTRYPOINT ["/init"] and keeping CMD ["/run.sh"].

## [0.1.2] - 2026-03-24

### Fixed

- Fix add-on startup by restoring Home Assistant base image init flow; replace ENTRYPOINT with CMD.

## [0.1.1] - 2026-03-24

### Fixed

- Rewrote add-on packaging files as true multiline text with LF newlines.
- Corrected Home Assistant repository/add-on metadata formatting for Supervisor parsing.
- Rewrote Dockerfile, requirements.txt, and run.sh to prevent single-line blob failures.
- Removed dependency on prebuilt image field to ensure install uses local repository build.

## [0.1.0] - 2026-03-24

### Added

- Initial add-on scaffold (config.yaml, Dockerfile, build.yaml, run.sh).
- FastAPI application skeleton with admin UI routes.
- Music Assistant async client with token-based authentication.
- Alexa webhook router and AudioPlayer directive builders.
- Session store and token mapper for playback state.
- Setup, status, logs, config, and health admin pages.
- Diagnostics subsystem with health checks.
- Persistent JSON-file storage layer.
- Structured logging with secret redaction.
- Unit tests for health, config, MA client, status page, and session store.
