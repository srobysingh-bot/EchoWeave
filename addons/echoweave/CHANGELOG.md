# Changelog

All notable changes to EchoWeave will be documented in this file.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/).

## [0.1.8] - 2026-03-24

### Fixed

- Fix setup/config persistence roundtrip by wiring Config page to live ConfigService values and persisted updates.
- Display Music Assistant token presence as redacted indicator (`**** (set)`) instead of showing blank when configured.
- Switch MA validation to command-based `POST /api` requests and add command/url/status logging without exposing token values.
- Tighten stream/public endpoint health semantics to separate valid, reachable-but-invalid (for example HTTP 404), and unreachable states.
- Mark local HTTP public endpoints as local-test/non-production instead of Alexa-ready.
- Sync runtime and packaging version markers to `0.1.8`.

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
