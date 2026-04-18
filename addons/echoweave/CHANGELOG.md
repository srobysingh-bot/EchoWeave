# Changelog

All notable changes to EchoWeave will be documented in this file.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/).

## [0.3.69] - 2026-04-18

### Fixed

- **Root cause fix for stream 404:** MA's audio stream server runs on a separate port (8097), not the API port (8095), and uses URL format `/single/{session_id}/{queue_id}/{queue_item_id}/{player_id}.{fmt}`. EchoWeave was constructing URLs as `http://MA:8095/stream/{queue_id}/{queue_item_id}` — wrong port, wrong path, missing session_id and player_id. Added `_build_ma_stream_url()` method that queries queue session_id and player_id from MA, then constructs the correct stream server URL.
- Updated `_extract_flow_parts()` to parse the correct MA stream URL format with 5 path segments.
- Updated push-url handoff to extract `queue_id` from flow parts when available.

## [0.3.68] - 2026-04-18

### Fixed

- Fix stream 404 from MA: `_try_enqueue_search_result` with `skip_playback_start=True` now calls `play_media(option="add")` to actually add the item to MA's player queue before returning. Previously, the item was never enqueued in MA, so MA's `/stream/{queue_id}/{queue_item_id}` endpoint returned 404 for every request. After enqueue, the code looks up the real `queue_item_id` that MA assigned (the library item ID is not a valid queue item ID).
- Fix `command_dispatch.py` `prepare_play`: always attempt `build_stream_context` to pre-cache the resolved stream URL, even for items with provider URIs. Falls back to URI mapping cache only if stream pre-caching fails.
- Fix `stream_router.py`: when all stream candidate URLs return 404, clear the stale cache, re-resolve a fresh URL from MA via `get_stream_url`, and retry the stream fetch before giving up.

## [0.3.67] - 2026-04-18

### Fixed

- Fix stream 404: `_try_enqueue_search_result` (Alexa `skip_playback_start=True` path) now calls `_resolve_default_queue_id()` to obtain the real MA player queue ID (e.g. `upe8aacb9e766f`) instead of using the EchoWeave logical queue ID (`queue-staging`) as the synthetic `queue_id` and `origin_stream_path`. MA does not recognise EchoWeave's logical queue IDs and returned 404 for every stream candidate.
- Fix `get_stream_url` enqueue-add fallback: after enqueueing with `option=add`, if the item is found in the queue, return its stream URL using the real MA `queue_item_id` even when `streamdetails` is not yet populated. Also scan all queue items for a URI match as secondary fallback.
- Fix `get_stream_url` final fallback: use `_resolve_default_queue_id()` to get the real MA player queue ID instead of the logical EchoWeave `queue_id`, ensuring MA's HTTP stream proxy URL is valid.
- Fix `_request_worker_handoff`: accept optional `resolved_ma_queue_id` parameter; use it in place of `flow["session_id"]` (EchoWeave logical ID); build `origin_stream_path` as `/edge/stream/{queue_id}/{queue_item_id}` instead of forwarding MA's internal `/flow/...` path (which EchoWeave's stream handler does not serve).
- Fix `ma_push_url`: resolve real MA queue ID via `_resolve_default_queue_id()` before calling `_request_worker_handoff` and pass it as `resolved_ma_queue_id`.
- Fix `stream_router.py` safety guard: use `_resolve_default_queue_id()` when building the MA HTTP proxy fallback URL so the fallback does not inherit the logical EchoWeave queue ID.

## [0.3.66] - 2026-04-18

### Fixed

- Fix songs not playing: `get_stream_url()` was returning raw provider URIs (`apple_music://track/...`, `spotify://...`) instead of HTTP URLs, causing httpx to fail with "Request URL is missing an 'http://' or 'https://' protocol."
- `get_stream_url` now skips non-HTTP `item.uri` and `item.streamdetails.url` values and falls through to `player_queues/get_stream_url` command; final fallback uses `{ma_base_url}/stream/{queue_id}/{item_id}` (MA's built-in HTTP transcoding proxy).
- `command_dispatch.py`: never cache provider URIs as stream source URLs in `prepare_play`.
- `stream_router.py`: safety guard replaces any non-HTTP `origin_source_url` with MA's HTTP stream proxy before attempting to fetch; clears bad cached entries.
- `stream_router.py`: URI mapping fallback no longer caches non-HTTP values; sets `origin_source_url = None` so the safety guard can replace it.

## [0.3.65] - 2026-04-18

### Fixed

- Fix "home connector is offline" error caused by Cloudflare Durable Object eviction: `relayCommand` now waits up to 5 seconds for the connector WebSocket to reconnect before returning 503.
- Reduce WebSocket reconnect backoff from 2s/30s to 1s/15s so the add-on reconnects faster after DO eviction.
- Switch Quick Tunnel from QUIC to HTTP/2 (`--protocol http2`) to eliminate QUIC timeout instability on ARM/HA hosts.
- Add background tunnel health monitor in `run.sh` that auto-restarts `cloudflared` if the process crashes.
- Fix missing `ECHOWEAVE_CONNECTOR_BOOTSTRAP_SECRET` export in `run.sh` (was causing 401 Unauthorized on edge connector registration).
- Increase edge signature `max_age_seconds` from 60 to 300 to tolerate clock skew between Cloudflare edge and HA host.
- Add `recent_alexa_users` table to `schema.sql` (was missing, causing silent errors in the Alexa home-lookup fallback path).
- Unify version strings across `config.yaml`, `run.sh`, and `constants.py`.

## [0.3.64] - 2026-04-17

### Fixed

- Fix stream 530/502 error caused by stale Cloudflare Tunnel URL: addon now reports its current `origin_base_url` in every `resolve_stream` response via WebSocket.
- Worker dynamically uses the live tunnel URL from the addon instead of the potentially stale D1 value, and auto-updates D1 when the URLs differ.
- Resolve stream source URL from URI mapping cache during `resolve_stream` command for synthetic items (previously left empty, causing stream endpoint to re-resolve from scratch).
- Add diagnostic logging for 530 tunnel errors to clearly identify stale tunnel URLs.

## [0.3.63] - 2026-04-17

### Fixed

- Eliminate 3-6 second pre-caching delay in `prepare_play`: synthetic items (with provider URI) now store a lightweight URI mapping instead of calling `build_stream_context` which made 3+ failing HTTP calls to MA.
- Fix stream resolution for synthetic items: `get_stream_url` now checks URI mapping cache when `queue_item_id` is a numeric ID (not a URI), enabling the `music/item_by_uri` fallback.
- Add enqueue-with-add-option last-resort in `get_stream_url`: tries `player_queues/play_media` with `option=add` to populate queue without starting playback, then retries stream lookup.
- Add URI mapping fallback in stream router: when `build_stream_context` fails for synthetic items, checks URI mapping cache and retries via `get_stream_url` with URI-aware resolution.

## [0.3.62] - 2026-04-17

### Fixed

- Bypass `play_media` entirely for Alexa flow (`skip_playback_start=True`): MA's Alexa provider cannot command the Echo Dot (PlayerCommandFailed), causing 500/timeouts. Now constructs playable result directly from search results without enqueuing.
- Enhanced `get_stream_url` with URI-based fallback resolution via `music/item_by_uri` for synthetic items.
- Stream URL cache integration: check cache before queue lookup in `get_stream_url`.
- Removed invalid `playerqueues/play_media` command from fallback list (always returned 400).

## [0.3.61] - 2026-04-17

### Fixed

- Fix `player_queues/play_media` payload: use `media=uri` parameter matching MA 2.x API (was incorrectly sending `media_type` + `uri`/`item_id`).
- Auto-discover `queue_id` in query search path when none is provided — resolves empty `queue_id` causing enqueue to fail.
- Add `players/play_media` as additional fallback command for enqueue.

## [0.3.60] - 2026-04-17

### Fixed

- Fix MA `music/search` 500 errors: use `search_query` parameter key and singular media types (`track`, `artist`, `album`, `playlist`) matching MA 2.x API.
- Retry alternate command (`music.search`) on HTTP 500 in addition to 404.
- Check both singular and plural media type keys when extracting search results.

## [0.3.59] - 2026-04-17

### Changed

- Bump add-on version to `0.3.59`.

### Fixed

- Robust now-playing fallback: accept any player state with current_media (not just playing/paused), two-pass scan, extract media from more fields, use player's queue_id when none requested.
- Full diagnostic logging of every player during fallback scan for production debugging.
- Include current_media preview in player inventory snapshot.

## [0.3.58] - 2026-04-17

### Changed

- Bump add-on version to `0.3.58`.

### Fixed

- Fix queue_empty error: add player_id as queue candidate in auto-discovery (in MA, queue_id = player_id).
- Add skip_playback_start parameter for edge mode so Alexa AudioPlayer handles playback instead of MA sending PlayerCommandFailed.
- Add now-playing fallback: extract title/artist from active players and search MA library when queue is empty.
- Fix 6 pre-existing test failures in handoff and queue resolution mocks.

## [0.3.57] - 2026-04-17

### Changed

- Bump add-on version to `0.3.57`.
- Bump edge-worker version to `0.1.6`.

### Fixed

- Wire all Alexa intent handlers (Play, Pause, Resume, Next, Previous, Stop) to Music Assistant via QueueMapper/StreamResolver instead of returning stub text.
- Create PlaybackController module for physical button presses on Echo devices.
- Fix bidirectional state sync: pause/stop/next/previous now forward to MA so playback state stays consistent.
- Make playback_events.py resilient in edge mode with safe session store access.
- Fix edge-worker mock DB args shift causing connector registration test failure.
- Add bearer auth to `/v1/admin/debug-info` to prevent cross-tenant data leakage.
- Remove bootstrap secret from debug-info response payload.
- Stop logging full stream URLs/tokens to prevent replay from log access.
- Fix incomplete `AlexaRequestEnvelope` TypeScript type (missing sessionId, locale, application fields).
- Add `timeout_ms` type coercion in HomeSession durable object to handle string inputs safely.

## [0.3.56] - 2026-04-15

### Changed

- Bump add-on version to `0.3.56`.

### Fixed

- Implement Alexa skill-session bootstrap in `/ma/push-url` for MA UI Alexa starts without inbound request context, including bootstrap request/send/confirm/fail logging.
- Allow prototype-skill playback attachment when bootstrap confirms a fresh live Alexa context and emit `prototype_skill_play_attached_to_live_request` for successful attach path.
- Extend integration coverage for bootstrap success/failure paths and stabilize tests by clearing push-url coalescing state between cases.

## [0.3.55] - 2026-04-15

### Changed

- Bump add-on version to `0.3.55`.

### Fixed

- Enforce Alexa session-context control-path behavior for MA UI initiated playback: when no active Alexa request context exists, `/ma/push-url` returns explicit `ui_play_requires_active_alexa_skill_session` instead of attempting prototype-skill playback.
- Surface explicit UI status messaging that prototype-skill playback is request/response scoped and UI-start requires active skill session unless a separate provider/API start route is implemented.

## [0.3.54] - 2026-04-15

### Changed

- Bump add-on version to `0.3.54` for fix validation.

### Fixed

- Treat Alexa no-session UI start as control-path unsupported instead of stream failure: `/ma/push-url` now returns `ui_play_requires_active_alexa_skill_session` with explicit user-facing message when no live Alexa request context exists.
- Keep strict request-context guard for prototype-skill playback (`inbound_request_id` or recent probe required) and skip worker handoff/prototype attachment when context is missing.
- Add explicit session-context logs for this path: `alexa_request_context_missing`, `prototype_skill_response_skipped_no_active_request`, and `ui_play_not_supported_without_active_skill_session`.

## [0.3.53] - 2026-04-15

### Changed

- Bump add-on version to `0.3.53`.

## [0.3.52] - 2026-04-14

### Fixed

- Tighten prototype-skill invocation proof path: `/ma/push-url` now treats success as observed stream fetch OR `AudioPlayer.PlaybackStarted` callback.
- Replace assumption-style `alexa_audio_player_play_sent` marker with `alexa_audio_player_play_response_expected` to avoid false acceptance semantics.
- Improve cross-service correlation for play attempts with explicit `play_request_id`, `playback_started`, and `last_event_type` status signals.
- Keep strict AudioPlayer response validation and payload logging (`alexa_audio_player_play_response_built`, `alexa_audio_player_play_response_sent`, response payload log).

## [0.3.51] - 2026-04-14

### Fixed

- Republish add-on release with latest prototype-skill playback response path fixes.
- Includes strict AudioPlayer.Play response contract checks, response/fetch correlation telemetry, and no-fetch classification as `prototype_skill_play_response_invalid`.

## [0.3.50] - 2026-04-14

### Fixed

- Fix prototype-skill play response path by validating and logging the AudioPlayer contract (`AudioPlayer.Play` + `shouldEndSession: true`) before response is sent.
- Add explicit prototype-skill play response diagnostics (`alexa_audio_player_play_response_built`, `alexa_audio_player_play_response_sent`) with safe stream URL host/path summary.
- Add correlation fields/events between play response and first stream fetch (`play_request_id` claim, `alexa_stream_fetch_observed`) and AudioPlayer playback events handling logs.
- Reclassify no-fetch-after-play-response failures as `prototype_skill_play_response_invalid` in post-handoff path.

## [0.3.49] - 2026-04-14

### Fixed

- Remove Alexa post-handoff dependence on MA control start commands (`player_queues/play`, `players/cmd/play`) in `/ma/push-url` flow.
- Enforce strict proof-based success for Alexa start: require real stream fetch observation before returning success.
- Add explicit Alexa start confirmation/failure logs (`alexa_audio_player_play_sent`, `alexa_audio_player_playback_started`, `alexa_audio_player_playback_failed`, `alexa_stream_fetch_observed`, `alexa_start_nonfatal_removed`).

## [0.3.48] - 2026-04-14

### Fixed

- Add explicit `alexa_start_nonfatal_removed` log marker to confirm strict policy that post-handoff start is only successful after real stream-fetch/playback-start evidence.
- Preserve strict failure behavior for post-handoff start attempts when no stream fetch confirmation is observed.

## [0.3.47] - 2026-04-14

### Fixed

- Enforce strict Alexa post-handoff start success rule: `/ma/push-url` only returns success after real Worker stream fetch observation for the session.
- Remove non-fatal accepted path for failed post-handoff start attempts; failed start now reports `device_start_failed` with explicit `alexa_start_playback_failed` diagnostics.
- Validate queue resume target against player active queue context before `player_queues/play` in Alexa path; skip invalid/generated queue ids and log queue mismatch decisions.
- Add explicit Alexa start decision logs (`alexa_start_stream_fetch_observed`, `alexa_start_playback_started`, `alexa_start_playback_failed`).

## [0.3.46] - 2026-04-14

### Fixed

- Validate Alexa start queue before `player_queues/play` and skip invalid/generated queue ids that do not match the player active queue context.
- Prevent `/ma/push-url` fatal failure loop when post-handoff Alexa resume/play fails due queue mismatch; coalesce and keep session stable instead of triggering repeated new handoffs.
- Add Alexa start diagnostics for queue validation/coalescing path (`alexa_start_queue_validated`, `alexa_start_queue_mismatch`, `alexa_start_player_active_queue`, `alexa_start_attempt_skipped_invalid_queue`, `alexa_start_attempt_coalesced`, `alexa_start_final_result`).

## [0.3.45] - 2026-04-14

### Fixed

- Republish add-on package so Home Assistant update channel picks up the latest Alexa stream-stability fixes from `0.3.44`.
- Includes session-context-first stream resolution and suppression of legacy Alexa direct-play URL injection attempts.

## [0.3.44] - 2026-04-14

### Fixed

- Stop blocking connector `resolve_stream` on unsupported MA command `player_queues/get_stream_url` when session handoff already provides canonical `origin_stream_path`.
- Resolve Worker stream playback from session context first (`origin_stream_path`) and skip queue lookup dependency for playback-time stream resolution in this path.
- Add explicit resolve-stream diagnostics for session-context path and queue-lookup suppression (`resolve_stream_from_session_context`, `resolve_stream_queue_lookup_skipped`, `resolve_stream_queue_lookup_failed_but_session_used`).
- Suppress legacy Alexa direct-play URL injection commands during handoff (`player_queues/play_media`, `playerqueues/play_media`, `players/play_media`) and emit `legacy_direct_play_suppressed`.

## [0.3.43] - 2026-04-14

### Fixed

- Restore real Alexa playback-start trigger in the `/ma/push-url` Alexa handoff path by invoking MA direct URL playback command after Worker token handoff instead of treating handoff token creation as success.
- Add explicit Alexa device-start logs (`alexa_play_directive_sent`, `alexa_play_directive_result`) and fail handoff as `device_start_failed` when no `/v1/stream/:token` fetch is observed within a short verification window.
- Add Worker playback-start status tracking (`/v1/connectors/playback-start-status`) backed by HomeSession Durable Object state and mark stream fetch start from `/v1/stream/:token` requests.
- Add explicit Alexa playback lifecycle logs in add-on webhook handlers (`alexa_playback_started`, `alexa_playback_failed`, `alexa_playback_stopped`).

## [0.3.42] - 2026-04-14

### Fixed

- Refine Alexa source URL candidate construction to prioritize explicit codec/profile/metadata query hints (MP3 first, AAC second, Alexa profile hints, ICY metadata off) before extension-based fallbacks.
- Harden Alexa fallback-transcode fetch error handling in the edge stream proxy and emit explicit upstream fetch failure diagnostics for easier live verification.

## [0.3.41] - 2026-04-14

### Fixed

- Add Alexa on-the-fly MP3 fallback transcoding in edge stream proxy when upstream responses are not in Alexa-supported formats, while preserving Worker token flow and signed edge fetch path.
- Add `ffmpeg` runtime dependency to addon image for Alexa fallback transcoding.
- Add detailed playback-handoff step diagnostics in Worker connector handoff flow (`playback_handoff_step`) with elapsed timing and source format hints to simplify control-plane vs media-plane debugging.

## [0.3.40] - 2026-04-14

### Fixed

- Add Alexa client profile propagation through stream tokens and worker-to-add-on fetch headers to select Alexa-compatible stream responses without changing tokenized stream architecture.
- Add Alexa stream compatibility probing on add-on edge stream path, preferring MP3/AAC candidate URLs and rejecting unsupported content types for Alexa profile requests.
- Add stream diagnostics for format and fetch lifecycle (`alexa_stream_format_selected`, `alexa_stream_transcode_started`, `alexa_stream_response_content_type`, `worker_stream_fetch_started`, `worker_stream_first_byte_sent`, `worker_stream_fetch_failed`).

## [0.3.39] - 2026-04-14

### Fixed

- Enforce Worker-handoff-only playback path for Alexa `/ma/push-url` flow and suppress legacy direct URL fallback commands (`player_queues/play_media`, `players/play_media`, and public flow fallback) for Echo players.
- Add strict per-player (`home_id + player_id`) duplicate request coalescing with short-window session reuse, returning accepted/reused response instead of failing duplicate requests.
- Treat duplicate post-handoff requests as coalesced/reused sessions (not handoff failures) and add explicit logs for accepted start/final state snapshots.

## [0.3.38] - 2026-04-14

### Fixed

- Add per-player in-flight handoff lock/debounce for Alexa-targeted playback handoff to prevent overlapping push-url play attempts.
- Gate Alexa handoff success on immediate post-handoff queue readback (`queue_length >= 1`) before treating playback as accepted.
- Add request-id correlation and post-handoff diagnostics across edge `/alexa/intents` and `/ma/push-url` logs for single-click tracing.

## [0.3.37] - 2026-04-10

### Added

- Add correlated probe diagnostics for edge Alexa preflight: each `/alexa/intents` response now emits `probe_id`, timestamp, and explicit contract-check logs.
- Store latest probe state in registry and expose via `GET /debug/alexa-probe` for live debugging.
- Include latest probe correlation (`probe_id`, `probe_time`) in `/ma/push-url` receipt logs to prove probe-to-push transition timing.
- Add edge startup regression test for probe-state debug endpoint.

## [0.3.36] - 2026-04-10

### Fixed

- Expand edge `/alexa/intents` `AMAZON.ResumeIntent` utterances to include `play audio`, `start`, and `play` so MA `player.play` path can issue a playback-starting phrase instead of resume-only wording.
- Keep `PlayAudio` custom intent declaration and probe payload logging for end-to-end contract tracing.

## [0.3.35] - 2026-04-10

### Fixed

- Refine edge-mode `GET /alexa/intents` payload to include custom `PlayAudio` intent utterances (`play audio`, `start`, `play`) required by MA Alexa flow expectations.
- Remove non-essential `bridgeMode` field from `/alexa/intents` response to keep strict provider-compatible schema.
- Keep explicit per-probe payload logging (`edge_alexa_intents_probe response payload=...`) for live contract verification.

## [0.3.34] - 2026-04-10

### Fixed

- Exempt `POST /ma/push-url` from UI basic-auth middleware so MA Alexa provider callbacks are not blocked while UI auth remains enabled.
- Add explicit auth-deny logs in `AdminAuthMiddleware` to surface path-level auth blocks quickly during runtime debugging.
- Add regression test ensuring `/status` stays protected while `/ma/push-url` remains callable without UI credentials.

## [0.3.33] - 2026-04-10

### Fixed

- Update edge-mode `GET /alexa/intents` response to match Music Assistant Alexa provider contract (`invocationName` + `intents[]`) instead of generic probe payload.
- Add explicit structured logging of the exact `/alexa/intents` response body for live contract verification.
- Add regression test asserting edge-mode `/alexa/intents` contract payload fields.

## [0.3.32] - 2026-04-10

### Fixed

- Expose `GET /alexa/intents` compatibility probe in edge mode so Music Assistant preflight checks no longer fail with 404 before `/ma/push-url` callback flow.
- Keep full `/alexa` webhook unmounted in edge mode while still returning `200` for probe path.
- Add edge startup regression assertion for `/alexa/intents` route presence.

## [0.3.31] - 2026-04-10

### Fixed

- Add `/ma/push-url` retry path: if MA direct URL playback fails with Worker tokenized stream URL, retry once with the public tunnel playback URL.
- Add structured retry lifecycle logs (`ma_push_url_retry_with_public_url` and result) to make fallback outcomes explicit during runtime debugging.

## [0.3.30] - 2026-04-10

### Fixed

- Correct `/ma/push-url` MA handoff command payloads to match MA `player_queues/play_media` contract (`queue_id` + `media`) instead of legacy-only `media_type`/`uri` payloads.
- Prioritize MA player identifiers for direct URL queue targeting and de-prioritize flow session IDs passed as preferred queue hints.
- Add additional command payload variants (`media` string/list and no-option fallback) to improve compatibility across MA builds.
- Extend MA client tests to validate queue targeting and direct URL payload shape for handoff playback.

## [0.3.29] - 2026-04-10

### Fixed

- Prevent `/ma/push-url` crashes when MA queue-state command returns `null`/unexpected shape.
- Convert queue-state shape mismatch into controlled `MusicAssistantError` so handoff flow can continue with fallback attempts.
- Refresh MA client queue-state fallback test to align with command API mocks.

## [0.3.28] - 2026-04-10

### Fixed

- Improve edge push-url playback handoff by passing MA flow `session_id` as preferred queue id when starting direct URL playback.
- Add additional MA command fallback for direct URL playback using `players/play_media` namespace when `player_queues/play_media` fails.
- Expand handoff diagnostics with `preferred_queue_id` so queue selection mismatches are visible in logs.

## [0.3.27] - 2026-04-10

### Fixed

- Add Worker connector playback handoff endpoint to mint tokenized ` /v1/stream/:token` URLs for MA push-url initiated sessions.
- Update add-on `/ma/push-url` flow to request Worker handoff and use Worker tokenized URL as the final playback URL in edge mode.
- Add structured worker handoff logs for request sent, response, tokenized URL creation, and session-start result.
- Require direct URL playback success for edge-mode Alexa handoff and stop treating resume-only MA commands as primary playback proof.

## [0.3.26] - 2026-04-10

### Fixed

- Add runtime version/build metadata in `ma_push_url_received` logs to verify deployed add-on revision quickly.
- Log full matched MA player object and internal identifier fields during push-url handoff diagnostics.
- Preserve exact MA 5xx response body in command errors for actionable playback failure analysis.
- Gate `play_media` URL playback by capability signals and prefer resume triggers for Alexa/Echo-style players to avoid unsupported command retries.

## [0.3.25] - 2026-04-10

### Fixed

- Replace `/ma/push-url` acknowledge-only stub with real playback handoff flow.
- Convert incoming local MA flow URLs into public HTTPS playback URLs suitable for Alexa fetch behavior.
- Resolve target player from push payload/flow context and dispatch MA play-media plus play commands.
- Add structured handoff lifecycle logs for receipt, player resolution, URL construction, playback request dispatch/result, and failure reasons.

 
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
