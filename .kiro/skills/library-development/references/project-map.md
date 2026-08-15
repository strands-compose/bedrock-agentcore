# Library Project Map

Navigation aid for `src/strands_compose_agentcore/`. Exact file names may drift
over time -- trust the **roles** and the "read first" pointers more than any
single name.

## Layout

```
src/strands_compose_agentcore/
├── __init__.py          # PUBLIC API -- create_app, clients, media builders, types, exceptions
├── app.py               # BedrockAgentCoreApp factory, ASGI lifespan, /invocations entrypoint
├── session.py           # SessionState dataclass, resolve_session(), close_session(), run_entry_agent()
├── payload.py           # Server-side payload parser: validates prompt, decodes media, limits
├── types.py             # Public types: ContentBlock union, AgentInput, exception hierarchy, RetryConfig
├── media.py             # Client-side content block builders: text(), image(), document(), reply()
├── media_formats.py     # Canonical MediaFormatSpec registry (MEDIA_FORMATS tuple -- single source of truth)
├── _utils.py            # Internal: ansi(), validate_session_id(), error_event()
├── py.typed             # PEP 561 marker
├── client/
│   ├── __init__.py      # Re-exports: AgentCoreClient, LocalClient, AsyncLocalClient, exceptions
│   ├── agentcore.py     # AgentCoreClient: async boto3 (thread-offloaded), SSE streaming, retry
│   ├── local.py         # LocalClient (sync urllib) + AsyncLocalClient (httpx) -- both yield StreamEvent
│   ├── utils.py         # Shared: parse_sse_line(), translate_error(), build_invocation_body(), DEFAULT_SESSION_ID
│   └── repl.py          # run_repl() -- interactive loop with slash commands, AnsiRenderer
└── cli/
    ├── __init__.py      # CLI entry point: main(), _build_parser(), _ColorArgumentParser
    ├── dev.py           # cmd_dev(): server + REPL in one terminal, port check, health polling
    ├── client.py        # cmd_client(): local/remote REPL dispatch
    └── utils.py         # CLIError exception, ANSI colour helpers (red, reset)
```

## Where to read first, by task

| Task | Read these first |
|------|------------------|
| Understand the whole flow | `app.py` (factory + entrypoint) then `session.py` (lifecycle) |
| Add/change payload validation | `payload.py` -- self-contained, all parsing lives here |
| Session lifecycle or caching | `session.py` -- `resolve_session`, `close_session`, `run_entry_agent`, `SessionState` |
| New media format support | `media_formats.py` (add `MediaFormatSpec`) -- everything derives from it |
| Client-side media builders | `media.py` -- `text()`, `image()`, `document()`, `reply()` |
| New client transport | `client/local.py` or `client/agentcore.py` (pick closest pattern) |
| Client error handling | `client/utils.py` -- `translate_error` + `_ERROR_MAP` in `types.py` |
| SSE line parsing | `client/utils.py` -- `parse_sse_line()` |
| New exception type | `types.py` (define) + `client/utils.py` (map) + both `__init__.py` (export) |
| REPL behaviour/commands | `client/repl.py` -- `run_repl()` |
| New CLI command | `cli/dev.py` (pattern) then wire in `cli/__init__.py` |
| Session ID validation | `_utils.py` -- `validate_session_id()` |
| App wiring / CORS / lifespan | `app.py` -- `_make_lifespan`, `create_app` kwargs |
| Invocation locking / busy state | `app.py` entrypoint (lock check) + `session.py` (`SessionState.invocation_lock`) |
| Public API surface | `__init__.py` (top-level `__all__`) + `client/__init__.py` |

## Architectural invariants

Intended design law:

- **Config at boot, session on first invocation.** `create_app` calls
  `load_config` once (or accepts a pre-built `AppConfig`); `resolve_session` calls
  `load(app_config, session_id=…)` on the first request, once the session ID from
  the AgentCore header is known. The session is cached and reused until a new
  session ID arrives. Nothing live is built in the factory or the lifespan.
- **The session manifest is built once.** `resolve_session` stores it on
  `SessionState`; the entrypoint re-emits it with SESSION_START on every turn.
- **A replaced session is always closed.** The entrypoint calls `close_session`
  before swapping in a new one: `Agent.cleanup()` on every agent (and on delegate
  orchestrations, which are Agents) stops their MCP clients immediately. A
  delegated agent lives in an agent-as-tool reference cycle, so refcounting
  cannot reap it and its `command:` subprocess would survive until an arbitrary
  cyclic-GC pass. The lifespan has no teardown — process exit reaps the
  subprocess by itself.
- **Single-flight by design.** One invocation at a time per pod. Concurrent
  single-tenant invocations are rejected on purpose; multi-tenant concurrency is
  out of scope (AgentCore's microVM handles isolation). The invocation lock
  enforces this in local dev where no microVM exists; `/ping` reports
  `HEALTHY_BUSY` while locked. The busy-check → lock-acquire path has no `await`
  between it — preserve that.
- **Deliberate lockstep coupling with strands-compose.** Its types
  (`StreamEvent`, `ResolvedConfig`, `EventQueue`) are trusted, re-exported
  unchanged, and never wrapped or re-versioned. Upstream breaking changes are
  fixed here in the same release train, not shimmed. The only sanctioned deep
  imports are `manifest.build_manifest` and `types.SessionManifest`, both confined
  to `session.py`.
- **`MEDIA_FORMATS` is the sole format source of truth.** `IMAGE_FORMATS`,
  `DOCUMENT_FORMATS`, and the extension maps all derive from it. Add a format in
  one place only.
- **Single entrypoint pattern.** Exactly one `@app.entrypoint` async generator;
  all request handling, error recovery, and single-flight control live inside it.
  Because it `yield`s while a background run task is alive, it uses an explicit
  `asyncio.create_task` + `try/finally` (awaited on completion, cancelled-then-awaited
  on early exit) rather than a `TaskGroup` — yielding across a cancel scope is
  unsafe (PEP 789).
- **Error events, never HTTP errors.** Server failures emit one `type="error"`
  `StreamEvent` whose `data` mirrors the upstream error schema
  (`text` + `exception_type`, never an adapter-only `code`) and return
  normally; the SSE connection stays open for the single response.
- **Client contract is uniform.** All three clients accept `AgentInput` (str |
  ContentBlock | list[ContentBlock]) and yield `StreamEvent`. Wire shape is
  `{"prompt": ...}`. boto3 is bridged with `asyncio.to_thread` / a bounded
  executor; the loop is never blocked.
- **Exception hierarchy maps 1:1 to AWS error codes.** Each botocore error code
  has a typed `AgentCoreClientError` subclass; the error map is the mapping.
- **CLI uses `CLIError` for user-facing failures.** `main()` catches it, prints
  in red, and exits. Command handlers never call `sys.exit` directly.
- **Observability is the platform's.** AgentCore auto-instruments OTEL and
  ingests structured JSON logs; the adapter emits correlated key/value logs
  (never payload contents or secrets) rather than building its own tracing.

## Public API surface

Consumers import from the top-level package only:

```python
from strands_compose_agentcore import (
    create_app,                    # factory
    AgentCoreClient, LocalClient, AsyncLocalClient, StopSessionResult,  # clients
    text, image, document, reply,  # media builders
    MEDIA_FORMATS, MediaFormatSpec,  # format registry
    # types
    ContentBlock, AgentInput, TextBlock, ImageBlock, DocumentBlock, ReplyBlock,
    ImageFormat, DocumentFormat, IMAGE_FORMATS, DOCUMENT_FORMATS,
    # exceptions
    AgentCoreClientError, ClientConnectionError, AccessDeniedError,
    ThrottledError, SessionNotFoundError, InvalidRequestError,
    ConflictError, RetryableConflictError,
    # config
    RetryConfig,
)
```

The yielded event type, `StreamEvent`, is a strands-compose type re-exported as
part of this package's public surface (intentional lockstep coupling). Consumers
may import it from `strands_compose_agentcore`; the package tracks its shape in
lockstep with strands-compose rather than shielding callers from it.

## Dependencies (runtime)

| Package | Role |
|---------|------|
| `strands-compose` (>=0.10.0,<1.0.0) | Config parsing, resolution, streaming, rendering |
| `bedrock-agentcore` (>=1.6.1) | `BedrockAgentCoreApp`, `BedrockAgentCoreContext` |
| `httpx` (>=0.27.0) | `AsyncLocalClient` transport |
| `boto3` (transitive via bedrock-agentcore) | `AgentCoreClient` AWS calls |

## Stack notes

- **Python >= 3.11.** No explicit ruff/ty target-version configured.
- **ASGI app** via `BedrockAgentCoreApp` (inherits from Starlette).
- **Console scripts:** `sca` and `strands-compose-agentcore` both point to
  `strands_compose_agentcore.cli:main`.
- **Tooling:** ruff (lint + format), ty (type check), bandit (security),
  pytest + pytest-asyncio (auto mode) + pytest-cov + pytest-xdist --
  orchestrated through `just`, run via `uv run just ...`.
- **Packaging:** hatchling builds `src/strands_compose_agentcore`.
