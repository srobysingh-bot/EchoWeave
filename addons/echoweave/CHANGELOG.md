# Changelog

All notable changes to EchoWeave will be documented in this file.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/).

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
