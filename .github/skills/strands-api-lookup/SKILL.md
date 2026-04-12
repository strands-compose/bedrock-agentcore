---
name: strands-api-lookup
description: Look up strands and strands-compose APIs before implementing. Use this when working with strands Agent, strands-compose config loading, event streaming, converters, or session management.
---

# Strands and strands-compose API Lookup

Before implementing anything, check whether strands or strands-compose already provides it. This project is a **thin wrapper** — reimplementing upstream functionality is a rule violation.

## Import Rule

Always import from the **top-level** `strands_compose` package — never from submodules:

```python
# Good — top-level public API
from strands_compose import load_config, resolve_infra, load_session
from strands_compose import AppConfig, ResolvedConfig, ResolvedInfra
from strands_compose import EventQueue, StreamEvent

# Bad — reaching into submodules
from strands_compose.config.loaders import load_config      # DON'T
from strands_compose.config.resolvers import resolve_infra   # DON'T
```

The only exception is `validate_mcp` which lives under `strands_compose.startup`:

```python
from strands_compose.startup import validate_mcp
```

## Key APIs — Do NOT Reimplement

| What | Import | Purpose |
|------|--------|---------|
| `load_config()` | `from strands_compose import load_config` | Parse YAML into `AppConfig` |
| `resolve_infra()` | `from strands_compose import resolve_infra` | Resolve models, MCP servers, session managers |
| `load_session()` | `from strands_compose import load_session` | Create agents, orchestrations, entry point |
| `AppConfig` | `from strands_compose import AppConfig` | Parsed YAML config object |
| `ResolvedConfig` | `from strands_compose import ResolvedConfig` | Fully resolved configuration object |
| `ResolvedInfra` | `from strands_compose import ResolvedInfra` | Resolved infrastructure (models, MCP, sessions) |
| `EventQueue` / `StreamEvent` | `from strands_compose import EventQueue, StreamEvent` | Event streaming primitives |
| `AnsiRenderer` | `from strands_compose import AnsiRenderer` | Terminal-friendly event rendering |
| `validate_mcp()` | `from strands_compose.startup import validate_mcp` | Post-load MCP validation |
| `BedrockAgentCoreApp` | `from bedrock_agentcore import BedrockAgentCoreApp` | ASGI app with `/invocations` endpoint |
| `BedrockAgentCoreContext` | `from bedrock_agentcore.runtime.context import BedrockAgentCoreContext` | Session ID from runtime header |

## How to Check

1. Search the strands-compose public API:

```bash
uv run python -c "import strands_compose; print(dir(strands_compose))"
```

2. Check the strands Agent API:

```bash
uv run python -c "from strands import Agent; help(Agent)"
```

3. If the functionality exists upstream, import and use it directly from the top-level package.
4. If it does not exist, implement it in this project following `AGENTS.md` rules.

## Common Patterns

```python
from strands_compose import load_config, resolve_infra, load_session

# Load and resolve config
app_config = load_config("config.yaml")
infra = resolve_infra(app_config)

# Create session (agents, orchestrations, entry)
session = load_session(app_config, infra)
```
