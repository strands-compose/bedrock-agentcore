# Library Project Map

Navigation aid for `src/strands_compose_agentcore/`. Exact file names may drift
over time -- trust the **roles** and the "read first" pointers more than any
single name.

## Layout

```
src/strands_compose_agentcore/
├── __init__.py          # PUBLIC API -- create_app, clients, media builders, types, exceptions
├── app.py               # BedrockAgentCoreApp factory, ASGI lifespan, /invocations entrypoint
├── session.py           # SessionState dataclass, resolve_session(), run_entry_agent()
├── payload.py           # Server-side payload parser: validates prompt, decodes media, limits
├── types.py             # Public types: ContentBlock union, AgentInput, exception hierarchy, RetryConfig
├── media.py             # Client-side content block builders: text(), image(), document(), reply()
├── media_formats.py     # Canonical MediaFormatSpec registry (MEDIA_FORMATS tuple -- single source of truth)
├── _utils.py            # Internal: ansi(), validate_session_id(), error_event(), prepare_app_state()
├── py.typed             # PEP 561 marker
├── client/
│   ├── __init__.py      # Re-exports: AgentCoreClient, LocalClient, AsyncLocalClient, exceptions
│   ├── agentcore.py     # AgentCoreClient: async boto3 + ThreadPoolExecutor, SSE streaming, retry
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
| Session lifecycle or caching | `session.py` -- `resolve_session`, `run_entry_agent`, `SessionState` |
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

## Invariants observed in the codebase

- **Two-phase resolution is architectural law.** `resolve_infra` once at boot
  (models, MCP); `resolve_session` lazily on first invocation with the session
  ID from the AgentCore header. Session is cached and reused until a new
  session ID arrives.
- **`MEDIA_FORMATS` is the sole format source of truth.** `IMAGE_FORMATS`,
  `DOCUMENT_FORMATS`, `_IMAGE_EXTENSIONS`, `_DOCUMENT_EXTENSIONS` are all
  derived. Add a format in one place only.
- **Single entrypoint pattern.** The app has exactly one `@app.entrypoint`
  async generator. All request handling, error recovery, and concurrency
  control lives inside it.
- **Invocation lock prevents concurrency.** One agent invocation at a time per
  pod. Concurrent requests are rejected with an error event. `/ping` returns
  `HEALTHY_BUSY` while locked.
- **Error events, never HTTP errors.** Server failures emit a `StreamEvent`
  with `type="error"` and return normally from the generator. The SSE
  connection stays open for the single response.
- **Client contract is uniform.** All three clients accept `AgentInput` (str |
  ContentBlock | list[ContentBlock]) and yield `StreamEvent`. The wire shape is
  `{"prompt": ...}`.
- **Exception hierarchy maps 1:1 to AWS error codes.** Each botocore error
  code has a typed `AgentCoreClientError` subclass. `_ERROR_MAP` is the
  mapping.
- **CLI uses `CLIError` for user-facing failures.** `main()` catches it,
  prints in red, and exits. Command handlers never call `sys.exit` directly.

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

## Dependencies (runtime)

| Package | Role |
|---------|------|
| `strands-compose` (>=0.9.0,<1.0.0) | Config parsing, resolution, streaming, rendering |
| `bedrock-agentcore` (>=1.6.1) | `BedrockAgentCoreApp`, `BedrockAgentCoreContext` |
| `httpx` (>=0.27.0) | `AsyncLocalClient` transport |
| `boto3` (transitive via bedrock-agentcore) | `AgentCoreClient` AWS calls |

## Stack notes

- **Python >= 3.11.** Tooling targets 3.13 for ruff/ty.
- **ASGI app** via `BedrockAgentCoreApp` (inherits from Starlette).
- **Console scripts:** `sca` and `strands-compose-agentcore` both point to
  `strands_compose_agentcore.cli:main`.
- **Tooling:** ruff (lint + format), ty (type check), bandit (security),
  pytest + pytest-asyncio (auto mode) + pytest-cov + pytest-xdist --
  orchestrated through `just`, run via `uv run just ...`.
- **Packaging:** hatchling builds `src/strands_compose_agentcore`.
