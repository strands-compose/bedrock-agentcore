# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/),
and this project adheres to [Semantic Versioning](https://semver.org/).

## v0.6.0 (2026-06-20)

## v0.5.0 (2026-05-26)

### Feat

- **client**: add AsyncLocalClient with httpx native async streaming (#19)
- **client**: add raw_output flag to AgentCoreClient and LocalClient invoke()

## v0.4.0 (2026-05-24)

### Feat

- **app**: emit SESSION_START and SESSION_END on every invocation (#15)

## v0.3.1 (2026-05-24)

### Fix

- **app**: flush event queue only on session reuse (#14)

## v0.3.0 (2026-05-24)

### Feat

- **cli**: support multiple config files in dev command (#13)
- **client**: add stop_session to AgentCoreClient (#12)

### Refactor

- **session**: decouple invocation streaming and harden concurrency guard (#11)

## v0.2.1 (2026-05-22)

### Fix

- **app**: prevent logging propagation when suppressing runtime logging (#9)

## v0.2.0 (2026-05-21)

### Feat

- **multimodal**: add comprehensive image and document support with builders and payload parser

## v0.1.1 (2026-04-13)

### Fix

- pin botocore<1.42.88 as temporary workaround for s3transfer compat

## v0.1.0

Initial release.

### App Factory

- `create_app()` — single-call factory that wraps a strands-compose YAML config as a `BedrockAgentCoreApp` with `POST /invocations` and `GET /ping` endpoints
- Accepts a YAML file path, raw YAML string, list of paths, or a pre-built `AppConfig`
- Two-phase resolution: infrastructure resolved once at boot, agents created lazily on first invocation using the session ID from `X-Amzn-Bedrock-AgentCore-Runtime-Session-Id` header
- Session reuse — follow-up prompts reuse cached agents and conversation state
- Full SSE event streaming from agents via `EventQueue`
- Concurrent invocation guard with `asyncio.Lock`; `/ping` reports `HEALTHY_BUSY` while an invocation is running
- CORS origin configuration via `cors_origins` parameter
- Lifespan management: MCP servers started on boot, validated, and shut down on process exit

### CLI

- `sca dev` (alias: `strands-compose-agentcore dev`) — starts an HTTP server and an interactive REPL in one process for local development
  - `--config`, `--port`, `--session-id` options
  - Port availability check, health-check polling with 30 s timeout
- `sca client local` — REPL that connects to a running local server
  - `--url`, `--session-id` options
- `sca client remote` — REPL that invokes a deployed AgentCore agent via boto3
  - `--arn` (required), `--region`, `--session-id` options
- Shared REPL with `AnsiRenderer` typewriter output, TTY colour detection, and slash commands (`/help`, `/clear`, `/session`, `/exit`)

### Clients

- `LocalClient` — synchronous HTTP client using `urllib` (zero extra deps), streams SSE events in real time
- `AgentCoreClient` — async boto3 wrapper for invoking deployed agents with thread-pool concurrency
  - Session ID validation (33–256 chars per AgentCore API)
  - `payload_extras` for custom fields alongside `prompt`
- Typed exception hierarchy: `AgentCoreClientError`, `AccessDeniedError`, `ThrottledError`
- SSE line parser shared between both clients

### Examples & Documentation

- `01_quick_start` — minimal multi-agent config with dev CLI walkthrough
- `02_deploy` — end-to-end deployment guide: create files, test locally, deploy to AgentCore Runtime, connect remotely
- Eight-chapter documentation covering architecture, getting started, app factory, session & streaming, CLI, deployment (3 paths), client, and advanced topics
