# strands-compose-agentcore — Agent Instructions

This is **strands-compose-agentcore**: a deployment adapter that runs [strands-compose](https://github.com/strands-compose/sdk-python) YAML configs on [AWS Bedrock AgentCore Runtime](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/).

It reads a strands-compose YAML config, resolves infrastructure once at boot, creates agents lazily on the first invocation (using the session ID from the AgentCore Runtime header), and streams events back via SSE.

---

## Architecture — NON-NEGOTIABLE

1. **Strands-first** — always check strands and strands-compose before reimplementing. If they provide it, use it directly.
2. **Thin wrapper** — translate AgentCore Runtime conventions to strands-compose calls, then get out of the way.
3. **Composition over inheritance** — small, focused components that compose.
4. **Explicit over implicit** — no auto-registration, no global singletons.
5. **Single responsibility** — each module does one thing.
6. **Testable in isolation** — no global state, every unit testable without other components.

## Python Rules

- `from __future__ import annotations` at the top of every module.
- Every public function/method/class must be fully typed — parameters and return type.
- Use `X | None`, `X | Y`, `list`, `dict`, `tuple` — never `Optional`, `Union`, `List`, `Dict`.
- Google-style docstrings on every public class, function, and method.
- Class docstring goes on `__init__`, not the class body.  Exception: ``@dataclass`` classes (where ``__init__`` is generated) use the class body.
- Early returns always — handle edge cases first, max 3 nesting levels.
- Raise specific exceptions (`ValueError`, `KeyError`, `TypeError`, `RuntimeError`) with context.
- Never silently swallow exceptions. No bare `except:`.
- Return copies from properties: `return list(self._items)`.
- `logging.getLogger(__name__)` for diagnostics. Use `print()` for user-facing CLI and REPL output.
- No `eval()`, `exec()`, `pickle` for untrusted data, `subprocess(shell=True)`.
- No hardcoded secrets — use env vars.
- Import order: stdlib → third-party → local (ruff-enforced).
- `__all__` in `__init__.py` and submodule public API boundaries.

## Naming

- Classes: `PascalCase` | functions/methods: `snake_case` | constants: `UPPER_SNAKE_CASE` | private: `_prefix`
- No abbreviations in public API. Boolean params: `is_`, `has_`, `enable_` prefixes.

## Key APIs (do NOT reimplement)

Import from the **top-level** `strands_compose` package — never from submodules:

```python
# Good
from strands_compose import load_config, resolve_infra, load_session
from strands_compose import AppConfig, ResolvedConfig, ResolvedInfra
from strands_compose import EventQueue, StreamEvent

# Bad — don't reach into submodules
from strands_compose.config.loaders import load_config      # DON'T
```

| What | Import | Purpose |
|------|--------|---------|
| `load_config()` | `from strands_compose import load_config` | Parse YAML → `AppConfig` |
| `resolve_infra()` | `from strands_compose import resolve_infra` | Resolve models, MCP, session managers |
| `load_session()` | `from strands_compose import load_session` | Create agents, orchestrations, entry |
| `AppConfig` | `from strands_compose import AppConfig` | Parsed YAML config object |
| `ResolvedConfig` | `from strands_compose import ResolvedConfig` | Fully resolved config |
| `ResolvedInfra` | `from strands_compose import ResolvedInfra` | Resolved infrastructure |
| `EventQueue` / `StreamEvent` | `from strands_compose import EventQueue, StreamEvent` | Event streaming |
| `AnsiRenderer` | `from strands_compose import AnsiRenderer` | Terminal event rendering |
| `validate_mcp()` | `from strands_compose.startup import validate_mcp` | Post-load MCP validation (exception — not top-level) |
| `BedrockAgentCoreApp` | `from bedrock_agentcore import BedrockAgentCoreApp` | ASGI app with `/invocations` entrypoint |
| `BedrockAgentCoreContext` | `from bedrock_agentcore.runtime.context import BedrockAgentCoreContext` | Session ID from runtime header |

## Testing

- Every public function gets at least one test. Test behavior, not implementation.
- Use pytest fixtures, `parametrize`, `tmp_path`. Mock external dependencies.
- Name tests descriptively: `test_invoke_sync_translates_client_error`.

## Tooling

```bash
uv run just install      # install deps + git hooks (once after clone)
uv run just check        # lint + type check + security scan
uv run just test         # pytest with coverage (≥90%)
uv run just format       # auto-format with ruff
```

## Directory Structure

```
src/strands_compose_agentcore/
├── __init__.py          # Public API — create_app, client
├── _utils.py            # Internal ANSI/TTY helpers
├── app.py               # BedrockAgentCoreApp factory and lifespan
├── py.typed             # PEP 561 type-hint marker
├── session.py           # Session state, resolution, and streaming
├── cli/
│   ├── __init__.py      # CLI entry point — parser + dispatch
│   ├── utils.py         # Shared ANSI colour helpers, CLIError exception
│   ├── dev.py           # dev command (server + REPL in one process)
│   └── client.py        # client local/remote REPL dispatch
├── client/
│   ├── __init__.py      # Re-exports AgentCoreClient, LocalClient, exceptions
│   ├── utils.py         # Shared SSE line parsing, client error types
│   ├── agentcore.py     # Async boto3 client for invoking deployed agents
│   ├── local.py         # HTTP client for local server
│   └── repl.py          # Shared REPL loop

tests/
├── __init__.py
├── conftest.py          # Shared test fixtures and factory helpers
├── test_app.py          # App factory, lifespan, session streaming
├── test_app_invoke.py   # Invocation flow, concurrency, session handling
├── test_cli.py          # CLI parser and dispatch tests
├── test_client_agentcore.py  # AgentCoreClient tests
├── test_client_repl.py  # AgentCoreClient REPL tests
├── test_integration.py  # End-to-end Starlette TestClient tests
├── test_local_client.py # LocalClient tests
├── test_repl.py         # Shared REPL loop tests
└── test_sse.py          # SSE line parsing tests

docs/
├── README.md            # Table of contents
├── Chapter_01.md        # What Is This?
├── Chapter_02.md        # Getting Started
├── Chapter_03.md        # The App Factory
├── Chapter_04.md        # Session & Streaming
├── Chapter_05.md        # The CLI
├── Chapter_06.md        # Deployment
├── Chapter_07.md        # The Client
├── Chapter_08.md        # Advanced Topics
├── Chapter_09.md        # Deployment Strategies
└── Quick_Recipes.md     # AWS Tooling Reference

examples/
├── 01_quick_start/      # Multi-agent config + dev CLI — run and test locally
└── 02_deploy/           # End-to-end guide: create files → test → deploy → connect
```

## Logging Style

Use `%s` interpolation with structured field-value pairs — never f-strings:

```python
# Good
logger.info("session_id=<%s> | session resolved, agents ready", session_id)
logger.debug("line=<%s> | skipping non-JSON line", text[:120])

# Bad
logger.debug(f"Tool {tool_name} called")                # no f-strings
logger.info("Config loaded.")                           # no punctuation
```

- Field-value pairs first: `key=<value>` separated by commas
- Human-readable message after ` | `
- `<>` around values (makes empty values visible)
- Lowercase messages, no trailing punctuation
- `%s` format strings, not f-strings (lazy evaluation)

## Things to Do

- `from __future__ import annotations` at the top of every module
- Fully type every function signature (parameters + return type)
- Google-style docstring on every public class, function, and method
- Put class docstrings on `__init__`, not the class body.  Exception: ``@dataclass`` (use class body)
- Early returns — handle edge cases first, max 3 nesting levels
- Raise specific exceptions with context
- Use structured logging with `%s` and field-value pairs
- Run `uv run just check` then `uv run just test` before committing

## Things NOT to Do

- Don't reimplement what strands or strands-compose already provides — check first
- Don't use `Optional[X]`, `Union[X, Y]`, `List`, `Dict` — use `X | None`, `list`, `dict`
- Don't use `print()` for diagnostics — use `logging.getLogger(__name__)`. `print()` is fine for user-facing CLI and REPL output.
- Don't use f-strings in log calls — use `%s` interpolation
- Don't swallow exceptions silently — no bare `except:`
- Don't add `__all__` to private or internal modules — only in `__init__.py` and submodule public API boundaries
- Don't hardcode secrets — use env vars
- Don't use `eval()`, `exec()`, `pickle` for untrusted data, or `subprocess(shell=True)`
- Don't commit without running `uv run just check`
- Don't add comments about what changed or temporal context

## Agent-Specific Notes

- Make the **smallest reasonable change** to achieve the goal — don't refactor unrelated code
- Prefer simple, readable, maintainable solutions over clever ones
- Comments should explain **what** and **why**, never **when** or **how it changed**
- If you find something broken while working, fix it — don't leave it commented out
- Never add or change files outside the scope of the task
