# Chapter 03 — The App Factory

`create_app()` is the main API of strands-compose-agentcore. It takes a YAML config and returns a ready-to-run ASGI server that AgentCore Runtime can host.

## Basic Usage

```python
from pathlib import Path
from strands_compose_agentcore import create_app

app = create_app(Path(__file__).parent / "config.yaml")
```

That single call does three things: it parses the YAML into an `AppConfig` via `load_config()`, creates a `BedrockAgentCoreApp` with an ASGI lifespan that holds that config, and registers an `/invocations` entrypoint that handles agent invocations with SSE streaming.

## Signature

```python
def create_app(
    config: str | Path | list[str | Path] | AppConfig,
    *,
    cors_origins: list[str] | None = None,
    suppress_runtime_logging: bool = False,
    invocation_timeout: float | None = None,
    max_payload_bytes: int | None = 25 * 1024 * 1024,
    max_media_bytes: int = 20 * 1024 * 1024,
    max_media_blocks: int = 20,
) -> BedrockAgentCoreApp:
```

### Parameters

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `config` | `str \| Path \| list \| AppConfig` | required | YAML file path, list of paths, or pre-built `AppConfig` |
| `cors_origins` | `list[str] \| None` | `None` | Allowed CORS origins. Set to `["*"]` for local dev |
| `suppress_runtime_logging` | `bool` | `False` | Remove the JSON log handler on `bedrock_agentcore.app` logger |
| `invocation_timeout` | `float \| None` | `None` | Max seconds for a single invocation. `None` means no timeout |
| `max_payload_bytes` | `int \| None` | 25 MiB | Max JSON-serialized request body size. `None` disables the check |
| `max_media_bytes` | `int` | 20 MiB | Max decoded bytes for any single image or document block |
| `max_media_blocks` | `int` | `20` | Max number of image and document blocks per request |

### Config Input Formats

The `config` parameter accepts several formats:

```python
# Single file path
app = create_app("config.yaml")
app = create_app(Path("config.yaml"))

# Multiple file paths (merged)
app = create_app(["base.yaml", "agents.yaml"])

# Pre-built AppConfig
from strands_compose import load_config

config = load_config("config.yaml")
app = create_app(config)
```

When you pass multiple YAML files, collection sections (`models`, `agents`, `mcp_clients`, `orchestrations`) are merged, while singleton fields (`entry`, `session_manager`, `log_level`) use last-wins semantics. This is useful for separating shared model definitions from per-environment agent configs.

### Return Value

The factory returns a [`BedrockAgentCoreApp`](https://pypi.org/project/bedrock-agentcore/) instance — a [Starlette](https://www.starlette.io/)-based ASGI application with two endpoints:

- **`POST /invocations`** — agent invocations with SSE streaming response
- **`GET /ping`** — health check (returns `HEALTHY` or `HEALTHY_BUSY`)

For local development, call `app.run(port=8080)` to start it with uvicorn. In production on AgentCore Runtime, the runtime imports your module and discovers the `app` variable directly — you never call `run()` yourself.

## Config at Boot, Everything Live per Session

The factory separates *parsing* the config from *building* it. That follows from how AgentCore Runtime works: agents need a session ID to initialize their conversation history, and the session ID only arrives with the first request.

### At boot: validate the config

`create_app()` parses and validates the YAML immediately, so a malformed config fails before the server starts. The resulting `AppConfig` is pure data — no agents, no models, no MCP clients — and it is stashed on `app.state` so no YAML is re-read per session.

### On first invocation: build the session

When the first `POST /invocations` request arrives, the app reads the session ID from the `X-Amzn-Bedrock-AgentCore-Runtime-Session-Id` header and calls `load(app_config, session_id=...)` to build models, MCP clients, agents, orchestrations, and the entry point. An `EventQueue` is wired to all agents for streaming. This session state is cached — follow-up prompts within the same session reuse the same agents, preserving conversation history. Only the event queue is flushed between turns to discard stale events.

If a request arrives with a *different* session ID while the server is idle, the old session is closed (`Agent.cleanup()` on each agent, releasing its MCP clients and any `command:` subprocess) and a fresh one is built. On AgentCore Runtime this is expected — each session gets its own microVM, so a different session ID means routing has changed.

## The `/invocations` Entrypoint

Each request goes through this sequence:

1. **Validate** — checks that the JSON payload contains a `prompt` key whose value is a string, a single content block, or a list of content blocks
2. **Concurrency guard** — if an invocation is already in progress, rejects the request with an error event and reports `HEALTHY_BUSY` on `/ping` so AgentCore Runtime can back off
3. **Resolve session** — builds every live object on the first call, reuses them on subsequent calls within the same session
4. **Stream** — runs the entry agent asynchronously and yields `StreamEvent` dicts as Server-Sent Events

### Request and Response

Send a JSON payload with a `prompt` field:

```json
{"prompt": "Your message here"}
```

The response is a stream of Server-Sent Events. Each line is a JSON-serialized `StreamEvent`:

```
data: {"type": "token", "agent_name": "assistant", "timestamp": "...", "data": {"text": "Hello"}}
data: {"type": "tool_start", "agent_name": "assistant", "timestamp": "...", "data": {...}}
data: {"type": "tool_end", "agent_name": "assistant", "timestamp": "...", "data": {...}}
data: {"type": "agent_complete", "agent_name": "assistant", "timestamp": "...", "data": {...}}
```

## CORS and Logging

For local development with browser-based UIs, enable CORS by passing `cors_origins=["*"]`. The `dev` CLI command does this automatically.

The `BedrockAgentCoreApp` installs a JSON-formatted `StreamHandler` on the `bedrock_agentcore.app` logger. In production on AgentCore Runtime, this produces structured logs that [CloudWatch](https://docs.aws.amazon.com/AmazonCloudWatch/latest/logs/) can parse and filter — leave it enabled. During local development, this JSON output is noisy, so pass `suppress_runtime_logging=True` to remove it. Again, the `dev` command handles this for you.

## Next

[Chapter 04 — Session & Streaming](Chapter_04.md)
