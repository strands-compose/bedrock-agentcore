# Chapter 03 — The App Factory

`create_app()` is the main API of strands-compose-agentcore. It takes a YAML config and returns a ready-to-run ASGI server that AgentCore Runtime can host.

## Basic Usage

```python
from pathlib import Path
from strands_compose_agentcore import create_app

app = create_app(Path(__file__).parent / "config.yaml")
```

That single call does four things: it parses the YAML into an `AppConfig` via `load_config()`, resolves models, MCP servers/clients, and session managers via `resolve_infra()`, creates a `BedrockAgentCoreApp` with an ASGI lifespan that manages MCP infrastructure, and registers an `/invocations` entrypoint that handles agent invocations with SSE streaming.

## Signature

```python
def create_app(
    config: str | Path | list[str | Path] | AppConfig,
    infra: ResolvedInfra | None = None,
    *,
    cors_origins: list[str] | None = None,
    suppress_runtime_logging: bool = False,
) -> BedrockAgentCoreApp:
```

### Parameters

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `config` | `str \| Path \| list \| AppConfig` | required | YAML file path, list of paths, or pre-built `AppConfig` |
| `infra` | `ResolvedInfra \| None` | `None` | Pre-resolved infrastructure. `None` calls `resolve_infra()` automatically |
| `cors_origins` | `list[str] \| None` | `None` | Allowed CORS origins. Set to `["*"]` for local dev |
| `suppress_runtime_logging` | `bool` | `False` | Remove the JSON log handler on `bedrock_agentcore.app` logger |

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

When you pass multiple YAML files, collection sections (`models`, `agents`, `mcp_servers`, `mcp_clients`, `orchestrations`) are merged, while singleton fields (`entry`, `session_manager`, `log_level`) use last-wins semantics. This is useful for separating shared model definitions from per-environment agent configs.

### Return Value

The factory returns a [`BedrockAgentCoreApp`](https://pypi.org/project/bedrock-agentcore/) instance — a [Starlette](https://www.starlette.io/)-based ASGI application with two endpoints:

- **`POST /invocations`** — agent invocations with SSE streaming response
- **`GET /ping`** — health check (returns `HEALTHY` or `HEALTHY_BUSY`)

For local development, call `app.run(port=8080)` to start it with uvicorn. In production on AgentCore Runtime, the runtime imports your module and discovers the `app` variable directly — you never call `run()` yourself.

## Two-Phase Resolution

The factory implements a strict separation between infrastructure and session state. This is not an arbitrary design choice — it follows from how AgentCore Runtime works. Models and MCP connections are expensive to create and should be shared across all requests, while agents need a session ID (which only arrives with the first request) to initialize their conversation history.

### Phase 1: Infrastructure (at boot)

When the ASGI lifespan starts, strands-compose enters its MCP lifecycle: stdio-based MCP servers are launched, SSE-based MCP clients connect to their targets, and a validation report is printed summarizing available tools. The resolved infrastructure — models, MCP connections, and session managers — is stored in `app.state` and shared across all invocations. No agents exist yet.

### Phase 2: Session (on first invocation)

When the first `POST /invocations` request arrives, the app reads the session ID from the `X-Amzn-Bedrock-AgentCore-Runtime-Session-Id` header and calls `load_session(app_config, infra, session_id=...)` to create agents, orchestrations, and the entry point. An `EventQueue` is wired to all agents for streaming. This session state is cached — follow-up prompts within the same session reuse the same agents, preserving conversation history. Only the event queue is flushed between turns to discard stale events.

If a request arrives with a *different* session ID while the server is idle, the old session is discarded and a fresh one is created. On AgentCore Runtime this is expected — each session gets its own microVM, so a different session ID means routing has changed.

## The `/invocations` Entrypoint

Each request goes through this sequence:

1. **Validate** — checks that `prompt` exists in the JSON payload
2. **Concurrency guard** — if an invocation is already in progress, rejects the request with an error event and reports `HEALTHY_BUSY` on `/ping` so AgentCore Runtime can back off
3. **Resolve session** — creates agents on first call (lazy), reuses on subsequent calls within the same session
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
data: {"type": "complete", "agent_name": "assistant", "timestamp": "...", "data": {...}}
```

## CORS and Logging

For local development with browser-based UIs, enable CORS by passing `cors_origins=["*"]`. The `dev` CLI command does this automatically.

The `BedrockAgentCoreApp` installs a JSON-formatted `StreamHandler` on the `bedrock_agentcore.app` logger. In production on AgentCore Runtime, this produces structured logs that [CloudWatch](https://docs.aws.amazon.com/AmazonCloudWatch/latest/logs/) can parse and filter — leave it enabled. During local development, this JSON output is noisy, so pass `suppress_runtime_logging=True` to remove it. Again, the `dev` command handles this for you.

## Next

[Chapter 04 — Session & Streaming](Chapter_04.md)
