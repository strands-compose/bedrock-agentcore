---
name: library-development
description: Build and extend strands-compose-agentcore -- the deployment adapter that bridges strands-compose YAML configs to AWS Bedrock AgentCore Runtime. Use when adding or editing the app factory, session lifecycle, payload parsing, client transports, media helpers, CLI commands, or any server/client module. Source only; not tests, examples, or docs.
metadata:
  area: library
  stack: python,bedrock-agentcore,strands-compose,starlette,httpx,boto3
---

# Library Development

Rules for **strands-compose-agentcore** in `src/strands_compose_agentcore/`
(Python >= 3.11 + BedrockAgentCoreApp + strands-compose + httpx + boto3). They
describe the **mental model and conventions**, not the current set of files --
modules and features come and go, the shape stays.

strands-compose-agentcore does exactly one thing: **wrap a strands-compose YAML
config as a BedrockAgentCoreApp with SSE streaming, multimodal payloads, and a
client trio for invoking it.** All agent/model/tool/session resolution is
delegated to strands-compose. Before building anything that touches agent
wiring, event streaming, or config parsing, check the installed
strands-compose SDK (`.venv/lib/python*/site-packages/strands_compose/`) and
use what it provides. This package is a thin adapter on top, not a framework.

Before creating anything new, read a sibling that plays the same role and copy
its shape. Matching the existing pattern matters more than any rule below. See
`references/project-map.md` for where each role lives and what to read first --
load it whenever you are unsure where something goes.

---

## Core Principles -- NON-NEGOTIABLE

1. **strands-compose-first** -- if strands-compose or strands provides it, import and use it directly; never re-implement resolution, streaming, rendering, or config parsing.
2. **Thin adapter** -- translate AgentCore Runtime conventions (headers, payload shape, SSE response, boto3 API) to strands-compose calls, then get out of the way. Return strands-compose types (`StreamEvent`, `ResolvedConfig`, `EventQueue`), not wrappers.
3. **Two-phase resolution is the architecture** -- infrastructure once at boot (`resolve_infra`), session lazily on first invocation (`load_session`). Never blur this boundary.
4. **Explicit over implicit** -- no auto-registration, no global singletons, no hidden state. The app factory wires everything by hand; app state lives on `app.state`.
5. **Single responsibility** -- each module does one thing: payload parsing, session lifecycle, media encoding, client transport, REPL, CLI commands.
6. **Composition over inheritance** -- small functions and focused modules that compose. No base classes, no deep hierarchies.
7. **Smallest reasonable change** -- don't refactor unrelated code to land a feature.

---

## The Two-Phase Lifecycle -- the central mental model

Everything the adapter does revolves around a clear temporal split. Understand
this and you understand the whole package:

```
create_app(config)
  |
  +--> prepare_app_state(config, infra)
  |      load_config(config) -------> AppConfig        (strands-compose)
  |      resolve_infra(config) -----> ResolvedInfra    (models, MCP -- shared, cold)
  |
  +--> BedrockAgentCoreApp(lifespan=...)
         |
         +--> lifespan startup
         |      infra.mcp_lifecycle.start()            (MCP servers alive)
         |      validate_mcp(infra)                    (connectivity probed)
         |      app.state <- (app_config, infra, session=None)
         |
         +--> @app.entrypoint /invocations POST        (per-request)
                |
                +--> parse_payload(raw) ---------> AgentInput
                +--> validate_session_id(header)
                +--> resolve_session(config, infra, session_id) -+-> SessionState
                |      load_session(config, infra, session_id)   |   (agents, EventQueue, lock)
                |      resolved.wire_event_queue(session_id)     |
                |                                                |
                +--> session cached; reused for same session_id  |
                +--> events.flush() + emit_session_start(manifest)
                +--> run_entry_agent(resolved, events, input)
                |      resolved.entry.invoke_async(input)
                |      events -> StreamEvent -> yield asdict()
                +--> events.close(data=session_end_data)
```

Two hard boundaries:

- **Infra vs session.** `resolve_infra` builds process-lifetime things (models,
  MCP servers/clients, lifecycle) with no session context. `resolve_session`
  builds per-session things (agents, orchestrations, entry, EventQueue) using
  the session ID from the AgentCore header. One infra serves many sessions
  (sequentially in AgentCore's one-session-per-pod model, or if the pod is
  recycled for a new session). Never store agents on infra.
- **Server vs client.** The server side (`app.py`, `session.py`, `payload.py`,
  `_utils.py`) runs inside the AgentCore Runtime pod. The client side
  (`client/`) runs outside -- in user scripts, CLIs, or other services. They
  share only the wire contract (`{"prompt": ...}` + SSE `StreamEvent` dicts)
  and the `types.py` definitions.

---

## The Server Side -- app, session, payload

### `app.py` -- the factory

`create_app` is the one public entry point. It:
1. Calls `prepare_app_state` to resolve config + infra.
2. Builds a `BedrockAgentCoreApp` with a lifespan that starts MCP.
3. Registers the `@app.entrypoint` coroutine for `/invocations`.
4. Optionally adds CORS middleware.

The entrypoint is a single async generator that yields `StreamEvent.asdict()`
dicts. It handles: payload parsing, session ID validation, session
resolution/caching, invocation locking (one at a time per pod), busy
rejection, event flushing between turns, and graceful cancellation.

### `session.py` -- lifecycle

- `SessionState` dataclass: holds `resolved`, `events`, `session_id`, and
  `invocation_lock`.
- `resolve_session`: calls `load_session` + `wire_event_queue`, returns a
  `SessionState`.
- `run_entry_agent`: awaits `entry.invoke_async`, catches timeout + errors,
  emits error events, always closes the queue with session-end data.

### `payload.py` -- parsing

Validates the `{"prompt": ...}` wire shape. Decodes base64 media into native
bytes. Enforces size/count limits. Returns a `StrandsAgentInput`. All failures
raise `MultimodalPayloadError` (a `ValueError` subclass).

### `_utils.py` -- internal

`validate_session_id` (33-256 chars), `error_event` builder, `prepare_app_state`
(polymorphic config resolution), `ansi` TTY helper.

---

## The Client Side -- three transports, one contract

All three clients share the same input contract (`AgentInput = str |
ContentBlock | list[ContentBlock]`) and yield `StreamEvent` objects. They
differ only in transport:

| Client | Transport | Use case |
|--------|-----------|----------|
| `LocalClient` | sync `urllib` | Scripts, CLIs, sync tests |
| `AsyncLocalClient` | async `httpx` | Async servers, async tests |
| `AgentCoreClient` | async boto3 + `ThreadPoolExecutor` | Deployed agents, production |

Shared utilities in `client/utils.py`:
- `build_invocation_body` -- assembles `{"prompt": ...}` from `AgentInput`.
- `parse_sse_line` -- `"data: {...}"` -> `StreamEvent`.
- `translate_error` -- botocore `ClientError` -> typed exception hierarchy.

The REPL (`client/repl.py`) is shared across all three; each client provides a
`stream_fn` closure.

---

## Media -- format registry + client builders

The media subsystem has two halves:

- **`media_formats.py`** -- the single source of truth. `MEDIA_FORMATS` is a
  tuple of `MediaFormatSpec` dataclasses. Every other format set
  (`IMAGE_FORMATS`, `DOCUMENT_FORMATS`, `_IMAGE_EXTENSIONS`,
  `_DOCUMENT_EXTENSIONS`) is derived from it. To add a format, add one entry
  here -- everything else picks it up.
- **`media.py`** -- client-side builders: `text()`, `image()`, `document()`,
  `reply()`. They read local files, infer formats from extensions, base64-encode
  bytes, and return typed dicts matching the wire contract.

The server side (`payload.py`) re-validates and decodes these blocks. The two
sides are intentionally independent -- the builders trust the caller, the parser
trusts nothing.

---

## Types and Exceptions

`types.py` defines the public type vocabulary:
- Content blocks: `TextBlock`, `ImageBlock`, `DocumentBlock`, `ReplyBlock`,
  `ContentBlock` (union), `AgentInput` (union).
- Format literals: `ImageFormat`, `DocumentFormat`.
- Format sets: `IMAGE_FORMATS`, `DOCUMENT_FORMATS` (derived from registry).
- Exception hierarchy: `AgentCoreClientError` base with `ClientConnectionError`,
  `AccessDeniedError`, `ThrottledError`, `SessionNotFoundError`,
  `InvalidRequestError`, `ConflictError`, `RetryableConflictError`.
- `RetryConfig` dataclass for exponential backoff.

---

## CLI -- thin dispatch

`cli/__init__.py` builds the argparse tree and dispatches to command handlers.
Each command is a separate module:
- `cli/dev.py` -- `cmd_dev`: starts server in a daemon thread, polls `/ping`,
  launches REPL in the main thread.
- `cli/client.py` -- `cmd_client`: dispatches to `LocalClient.repl()` or
  `AgentCoreClient.repl()`.
- `cli/utils.py` -- `CLIError` exception, ANSI colour helpers.

`main()` catches `CLIError` and exits cleanly. Console scripts: `sca` and
`strands-compose-agentcore`.

---

## Python Conventions

- **`from __future__ import annotations`** at the top of every module.
- **Module docstring** describing the module's single responsibility.
- **Fully typed signatures** -- every function/method declares parameter and
  return types. Use `X | None`, `X | Y`, `list`, `dict`, `tuple` -- never
  `Optional`, `Union`, `List`, `Dict`.
- **Google-style docstrings** on every public class, function, and method, with
  `Args:` / `Returns:` / `Raises:`. Class docstrings go on `__init__` except
  `@dataclass` classes (use the class body).
- **Early returns** -- handle edge cases first; keep nesting <= 3 levels.
- **Raise specific exceptions** (`ValueError`, `TypeError`, `RuntimeError`,
  `MultimodalPayloadError`, `CLIError`, or a typed `AgentCoreClientError`
  subclass) with a contextual message.
- **Never swallow exceptions silently**; no bare `except:`. The sanctioned broad
  catch is best-effort cleanup (e.g. cancelling tasks, closing streams): catch
  `Exception`, log it, and continue.
- **`__all__` only in `__init__.py`** and `client/__init__.py` -- these are the
  public API surfaces.
- **Import order** stdlib -> third-party -> local (ruff-enforced, autofixed).
- Use `print()` **only** for user-facing CLI/REPL output. All diagnostics go
  through `logging.getLogger(__name__)`.
- Run modules with `uv run python ...`, never bare `python`.

---

## Logging

One module-level logger: `logger = logging.getLogger(__name__)`. Never
`print()` for diagnostics.

Use `%s` interpolation with structured field-value pairs -- never f-strings:

```python
logger.info("session_id=<%s> | session resolved, agents ready", session_id)
logger.warning("session_id=<%s>, busy_session_id=<%s> | invocation rejected", sid, cached.session_id)
```

- Field-value pairs first (`key=<value>`, comma-separated), human message after ` | `.
- `<>` around values (makes empty strings visible).
- Lowercase messages, no trailing punctuation.
- `%s` format args, not f-strings (lazy evaluation, hard rule).

---

## Adding to the Project -- Checklist

1. **Decide which side it belongs to** -- server (`app.py`, `session.py`,
   `payload.py`, `_utils.py`) or client (`client/`) or shared types
   (`types.py`, `media.py`, `media_formats.py`) or CLI (`cli/`). Unsure ->
   `references/project-map.md`.
2. **Read a sibling first.** Open an existing module of the same role and mirror
   its shape, docstrings, and error style.
3. **Check whether strands-compose already provides it.** Import from
   `strands_compose` top-level; never reach into submodules (exception:
   `strands_compose.startup.validate_mcp` and `strands_compose.manifest.build_manifest`).
4. **New media format?** Add one `MediaFormatSpec` entry to `MEDIA_FORMATS` --
   everything else derives from it.
5. **New exception?** Subclass `AgentCoreClientError` in `types.py`, add to
   `_ERROR_MAP` in `client/utils.py`, export from `client/__init__.py` and
   package `__init__.py`.
6. **New CLI command?** Add a `cmd_<name>` function in a new `cli/<name>.py`,
   wire it in `_build_parser`.
7. **Verify** before declaring done -- see Verify.

---

## Verify

Run from the repository root:

```bash
uv run just check    # ruff format-check + ruff lint + ty type-check + bandit
uv run just test     # pytest with --numprocesses=2 --cov --cov-fail-under=90
```

`just check` is the gate; it must pass before a change is done. If lint fails,
`uv run just format` first, then re-run. Do not start the app server to verify
-- rely on `check` and `test`.

---

## Things NOT to Do

- Don't re-implement what strands-compose or strands provides -- check first.
- Don't blur the infra/session boundary -- never store agents or session
  managers on `ResolvedInfra`, never resolve infrastructure per-request.
- Don't mix server concerns into client modules or vice versa.
- Don't add format tables outside `media_formats.py` -- derive from
  `MEDIA_FORMATS`.
- Don't mock or patch strands-compose internals in production code -- use the
  public API (`load_config`, `resolve_infra`, `load_session`).
- Don't use `Optional[X]` / `Union` / `List` / `Dict`, leave a signature
  untyped, or shadow a builtin.
- Don't `print()` for diagnostics -- use the logger with `%s` and field-value
  pairs. `print()` is reserved for CLI/REPL user output.
- Don't swallow exceptions silently or use bare `except:`.
- Don't add `__all__` outside `__init__.py` boundaries.
- Don't hardcode secrets; don't use `eval`/`exec`, `pickle` on untrusted data,
  or `subprocess(shell=True)`.
- Don't add files or folders outside the scope of the task.
- Don't leave broken or commented-out code.
- Comments explain **what** and **why**, never **when** or **how it changed**.
