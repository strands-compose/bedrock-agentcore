# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/),
and this project adheres to [Semantic Versioning](https://semver.org/).

## Unreleased

### Multimodal Payloads

- `/invocations` now accepts `prompt` (str), `content` (`list[ContentBlock]`) or `messages` (`list[Message]`) — exactly one is required
- Inline media via JSON-safe `source.base64` (decoded server-side to native `bytes`); S3 `source.location` is passed through unchanged
- New public `MultimodalPayloadError` raised on invalid payload shape
- `create_app()` gains `max_payload_bytes` (default 25 MiB), `max_media_bytes` (default 20 MiB), and `max_media_blocks` (default 20)
- New builder helpers in `strands_compose_agentcore.media`: `image_block`, `document_block`, `s3_image_block`, `s3_document_block`
- `LocalClient.invoke` and `AgentCoreClient.invoke` gain `content=` and `messages=` kwargs alongside the existing `prompt=`; `payload_extras=` still works for forward-compat
- `MultiAgentBase` entries reject full `messages` conversations with a structured error
- New example: `examples/03_multimodal/` (vision-capable single agent + client script)
- New chapter section: `docs/Chapter_04.md` — "Multimodal Payloads"

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
