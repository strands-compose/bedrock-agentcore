---
name: library-development
description: Build and extend strands-compose-agentcore -- the deployment adapter that bridges strands-compose YAML configs to AWS Bedrock AgentCore Runtime. Use when adding or editing the app factory, session lifecycle, payload parsing, client transports, media helpers, CLI commands, or any server/client module. Source only; not tests, examples, or docs.
metadata:
  area: library
  stack: python-3.11+,bedrock-agentcore,strands-compose,starlette,httpx,boto3
---

# Library Development

The mental model and conventions for **strands-compose-agentcore**
(`src/strands_compose_agentcore/`). This file teaches **how to think about the
package and what patterns to reach for**. For where a given role lives and what
to read first, load `references/project-map.md`.

strands-compose-agentcore does exactly one thing: **wrap a strands-compose YAML
config as a `BedrockAgentCoreApp` with SSE streaming, multimodal payloads, and a
client trio for invoking it.** All agent/model/tool/session resolution belongs
to strands-compose. This package translates AgentCore Runtime conventions
(headers, payload shape, SSE response, boto3 API) into strands-compose calls and
gets out of the way. It is a thin adapter, not a framework.

Before building anything that touches agent wiring, event streaming, or config
parsing, read the installed `strands_compose` source and use what it provides.
Then read a sibling that plays the same role and copy its shape — matching the
established pattern matters more than any single rule below.

---

## Core Principles — NON-NEGOTIABLE

1. **strands-compose-first.** If strands-compose or strands provides it, import
   and use it directly. Never re-implement resolution, streaming, rendering, or
   config parsing.
2. **Thin adapter, deliberate coupling.** Translate AgentCore conventions to
   strands-compose calls, then step aside. Pass through and re-export
   strands-compose types (`StreamEvent`, `ResolvedConfig`, `EventQueue`); do not
   wrap, shim, or re-version them. This coupling is intentional (see *Coupling
   with strands-compose*).
3. **Config at boot, session on first invocation.** `load_config` validates once
   in the factory; `load(app_config, session_id=…)` builds everything live on
   the first request. Never blur this boundary, and never resolve live objects
   in the factory or the lifespan.
4. **Single-flight by design.** One invocation at a time per pod. Concurrent
   single-tenant invocations are rejected on purpose; multi-tenant concurrency
   is out of scope (see *The Single-Flight Model*).
5. **Explicit over implicit.** No auto-registration, no hidden global singletons.
   The factory wires everything by hand. The one piece of request-scoped shared
   state (the cached session on `app.state`) is deliberate, lock-guarded, and
   documented — not incidental.
6. **Single responsibility; composition over inheritance.** Small focused
   modules and functions that compose. No base classes, no deep hierarchies.
7. **Structured concurrency.** Target 3.11+ and use the stdlib primitives —
   `asyncio.TaskGroup`, `asyncio.timeout`, `asyncio.to_thread`, `X | None`.
   Don't hand-roll task, thread, or queue plumbing the stdlib provides (see
   *Async & Concurrency*).
8. **Smallest reasonable change.** Don't refactor unrelated code to land a
   feature.

---

## The Config/Session Lifecycle — the central mental model

Everything the adapter does revolves around one split: the config is data
validated at boot; everything live belongs to a session.

```
create_app(config)
  ├─ load_config -> AppConfig                       pure data, no live objects
  └─ BedrockAgentCoreApp(lifespan=...)
       ├─ lifespan: stash (app_config, session=None) on app.state; no teardown
       └─ @app.entrypoint  /invocations POST  (per request)
             parse_payload -> validate_session_id -> resolve_session (cached)
             -> flush + emit session_start -> run_entry_agent -> close(session_end)
```

`resolve_session` is the whole of session construction: `load(app_config,
session_id=…)` builds models, MCP clients, agents, and orchestrations;
`build_manifest` describes the resulting topology once; `make_event_queue`
attaches the `EventPublisher` hooks. The manifest is stored on `SessionState` and
re-emitted with SESSION_START on every turn, so it is built exactly once per
session.

Two hard boundaries:

- **Config vs session.** The factory validates the YAML once so a malformed
  config fails before the server starts; the `AppConfig` it produces is pure
  data and is kept on `app.state` so no YAML is re-read per session.
  `resolve_session` runs on the first request, once the session ID from the
  AgentCore header is known, and is then cached and replaced only when a new
  session ID arrives. A replaced session is closed first
  (`close_session` → `Agent.cleanup()`): a delegated agent sits in an
  agent-as-tool reference cycle, so refcounting cannot reap it and its MCP
  `command:` subprocess would outlive the session until an arbitrary later
  cyclic-GC pass. **Never build live objects in the factory or the lifespan, and
  never replace a cached session without closing it.**
- **Server vs client.** The server side runs inside the AgentCore pod; the
  client side runs outside (user scripts, CLIs, other services). They share only
  the wire contract (`{"prompt": ...}` + SSE `StreamEvent` dicts) and the public
  `types`. Never mix server concerns into client modules or vice versa.

---

## The Single-Flight Model — concurrency is deliberately not offered

This is an explicit design decision, not an omission:

- **One invocation at a time, per pod.** AgentCore allocates one microVM per
  session, so cross-tenant isolation and multi-tenant concurrency are the
  platform's job, not ours. We do not build for multi-tenant concurrency, and we
  do not allow concurrent single-tenant invocations.
- **The invocation lock enforces single-flight where the platform can't.** In
  local development there is no microVM, so a caller could fire a second
  `/invocations` before the first finishes. The lock rejects the second request
  with an error event and `/ping` reports `HEALTHY_BUSY` so the runtime backs
  off. Keep the lock; it is the local-dev guarantee of the production invariant.
- **The cached session on `app.state` is the one sanctioned piece of shared
  mutable state.** Because there is exactly one in-flight invocation, reasoning
  about it stays simple: snapshot it once, and hold the lock across the run.
  Preserve the "no `await` between the busy-check and the lock acquire" property
  when editing the entrypoint — that is what makes the single-flight guarantee
  correct on a single-threaded event loop.
- **Do not add parallel-invocation support, work queues, or per-request agent
  pools.** If a use case seems to need them, it belongs upstream or in a
  different deployment shape, not here.

---

## Coupling with strands-compose — intentional, lockstep, single source of truth

This package and strands-compose are maintained in parallel and released in
lockstep (`strands-compose >=0.10.0,<1.0.0`). Treat that coupling as a feature:

- **Trust strands-compose types and re-export them unchanged.** The clients
  yield `StreamEvent`; the server passes `ResolvedConfig`/`EventQueue` around.
  Re-export the strands-compose types that appear in our public API so they are
  part of *our* declared surface, but never wrap, subclass, or re-version them.
  One source of truth beats a defensive shim.
- **We accept the maintenance contract.** A breaking change to a strands-compose
  contract is fixed here immediately, in the same release train. Do not add
  compatibility shims, feature detection, version branches, or duck-typed
  fallbacks to soften upstream changes — that would fork the source of truth.
- **Two sanctioned deep imports**, both confined to `session.py`:
  `strands_compose.manifest.build_manifest` and
  `strands_compose.types.SessionManifest`. They are the only session-topology
  pieces strands-compose does not surface at top level; keeping them in one
  module means one place to update if they move. Everything else comes from the
  `strands_compose` top level.

---

## Async & Concurrency — structured, cancellable, bounded

The adapter's core is a streaming pipeline; treat its concurrency with care.

- **Structured concurrency for the invocation — with one deliberate exception.**
  Prefer `asyncio.TaskGroup` and `asyncio.timeout` (3.11+) over bare
  `create_task` + manual bookkeeping. **Exception:** the `/invocations`
  entrypoint is an *async generator* that `yield`s SSE events while a
  background run task is alive. Holding a `TaskGroup` (or `asyncio.timeout`)
  open *across a `yield`* is unsafe — a cancel scope suspended at a yield can
  mis-scope or swallow cancellations (the motivation behind PEP 789; Trio
  forbids it outright). So the entrypoint deliberately uses an explicit
  `asyncio.create_task` guarded by `try/finally` that awaits the task on normal
  completion and cancels-then-awaits it on early exit (consumer disconnect).
  This is the sanctioned pattern for driving a background task from an
  async-generator entrypoint — keep it. Non-generator coroutines (e.g.
  `run_entry_agent`) have no yield boundary, so they use `asyncio.timeout`
  normally. The run task must always be awaited or cancelled; never orphan it.
- **Cancellation is a first-class path.** When the consumer disconnects
  mid-stream, the run task is cancelled and awaited, and the queue is closed. Let
  `CancelledError` propagate after cleanup; never swallow it.
- **Bridge sync boto3 with `asyncio.to_thread`.** boto3 is blocking; wrap its
  calls so the event loop is never stalled. A dedicated bounded executor is
  justified only when a client fans out many concurrent streams — keep it bounded
  and shut it down on close. Don't hand-roll thread/queue plumbing the stdlib
  provides.
- **Server-side blocking is already isolated — don't "fix" it.** The entrypoint
  runs on a worker loop in a background thread, and `/ping` is a sync Starlette
  handler served from a threadpool, so a blocking call in `resolve_session`
  (`MCPClient.start()` waits up to its 30 s `startup_timeout`) does not starve
  health checks — measured: 12/12 pings answered, 4.3 ms worst, during a 3 s
  block. Keep `resolve_session` / `close_session` sync. Wrapping them in
  `to_thread` buys nothing (the request awaits the same wall clock) and inserts
  an `await` into the busy-check → lock-acquire window, breaking single-flight.
- **Respect backpressure; never buffer unboundedly.** The event stream can be
  long-lived. Drain the queue as events arrive and yield straight through; do not
  accumulate events in an unbounded list. Queue mechanics belong to
  strands-compose — do not add a second, unbounded buffer of your own.

---

## The Wire Contract — one shape, two sides, typed errors

The client and server must never drift on the wire. The contract is:

- **Request:** a single `{"prompt": ...}` key whose value is a `str`, one content
  block, or a non-empty list of blocks. This matches the AgentCore `/invocations`
  JSON input; AgentCore passes the body through unvalidated, so **payload
  validation is our responsibility.**
- **Client → wire:** `build_invocation_body` assembles the body; the `media`
  builders produce blocks. Builders trust the caller.
- **Wire → server:** `parse_payload` validates shape, decodes base64 media into
  native bytes, enforces size/count limits, and raises `MultimodalPayloadError`.
  The parser trusts nothing.
- **Response:** SSE `StreamEvent` dicts, one per line. Failures do not become HTTP
  errors — they become a single `type="error"` event and the generator returns
  normally, keeping the SSE connection intact for the one response.
- **Error events mirror the upstream error schema — do not fork it.** When
  strands-compose emits an agent-level ``ERROR`` event it carries
  ``data={"text": <human message>, "exception_type": <class name>}`` (see
  ``strands_compose.hooks.event_publisher``). Adapter-level error events must
  use the **same two keys** so a single consumer can branch on
  ``exception_type`` regardless of whether the failure came from the agent or
  the adapter. Pass ``type(exc).__name__`` for real exceptions or a stable
  synthetic token (e.g. ``"AgentBusy"``) for adapter-originated errors. Never
  invent an adapter-only discriminator field (there is no ``code`` in the
  strands-compose contract) — that would fork the single source of truth the
  clients render against.

---

## Media — one registry, derive everything

- **`MEDIA_FORMATS` is the single source of truth.** Every other format set
  (`IMAGE_FORMATS`, `DOCUMENT_FORMATS`, extension maps) derives from it. To add a
  format, add one `MediaFormatSpec` entry — nothing else changes.
- **Builders trust, parser verifies.** Client-side builders read files, infer
  formats, and base64-encode. The server-side parser re-validates and decodes.
  The two sides are intentionally independent.

---

## Types and Exceptions

- **Public type vocabulary lives in one place** (`types`): content-block types,
  format literals, the derived format sets, the exception hierarchy, and config
  dataclasses.
- **One base exception, typed subtypes.** `AgentCoreClientError` is the base
  callers can catch; each AWS error code maps 1:1 to a subclass via the error
  map. Subtypes carry actionable meaning (access denied, throttled, not found,
  conflict, retryable conflict). Prefer built-in exceptions for generic failures
  (`ValueError`, `TypeError`); reach for a custom type only for a domain-specific
  contract.
- **Give exceptions the context callers act on** — a stable code and the offending
  identifier — not a prose sentence that tests or callers must match.

---

## Observability & Logging — structured, correlated, secret-free

The adapter runs inside AgentCore, which auto-instruments OpenTelemetry and
ingests logs as JSON. Work with the platform, not around it:

- **Do not reinvent tracing.** AgentCore/OTEL provides the trace backbone. Emit
  spans/attributes through the platform's instrumentation rather than building a
  parallel tracing layer.
- **Log structured, greppable key/value fields**, and always include the
  correlating `session_id` where available. The platform's JSON handler turns
  these into queryable fields; in local dev they stay human-readable.
- **One module logger** (`logging.getLogger(__name__)`); **`print()` only for
  CLI/REPL user output.**
- **`%s` lazy interpolation, never f-strings** in log calls (avoids formatting
  cost when the level is disabled). Field-value pairs first (`key=<value>`,
  comma-separated), human message after ` | `; `<>` around values so empty
  strings are visible; lowercase, no trailing punctuation.
- **Never log payload contents, media bytes, credentials, or tokens.** Log
  shapes, sizes, types, and identifiers — not user data.

```python
logger.info("session_id=<%s> | session resolved, agents ready", session_id)
logger.warning("session_id=<%s>, busy_session_id=<%s> | invocation rejected", sid, busy)
```

---

## Security

- **Payload limits are a DoS boundary, not a nicety.** `max_payload_bytes`,
  `max_media_bytes`, and `max_media_blocks` cap attacker-controlled input; keep
  them enforced in the parser and reject over-limit input before decoding.
- **Rely on the microVM for isolation.** Each session runs in its own microVM
  with an isolated CPU/memory/filesystem that is destroyed after the session, so
  the adapter does not re-defend that boundary — but it also must not weaken it
  (no cross-session caching of user data, no writing secrets to disk).
- **No `eval`/`exec`, no `pickle` on untrusted data, no `subprocess(shell=True)`,
  no hardcoded secrets.** Validate everything crossing the wire.

---

## Python Conventions

- **`from __future__ import annotations`** at the top of every module.
- **Module docstring** stating the module's single responsibility.
- **Fully typed signatures.** Use `X | None`, `X | Y`, `list`, `dict`, `tuple` —
  never `Optional`, `Union`, `List`, `Dict`. On 3.12+, prefer the `type`
  statement (PEP 695) for aliases; on 3.11 use `TypeAlias`.
- **Google-style docstrings** on every public class, function, and method
  (`Args:` / `Returns:` / `Raises:`). Class docstrings on `__init__` except
  `@dataclass` (use the class body).
- **Early returns; nesting ≤ 3 levels.**
- **`isinstance` against the real type, never duck typing.** No
  `getattr(x, "method", None)` / `hasattr` probing to tolerate a shape that might
  not be there — the dependency versions are pinned, so the type is known.
- **No defensive checks a validated type already guarantees.** If pydantic
  requires a field, don't re-check it.
- **Raise specific exceptions with context.** Never swallow silently; no bare
  `except:`. The only sanctioned broad catch is best-effort cleanup (cancelling
  tasks, closing streams): catch `Exception`, log it, continue — and re-raise
  `CancelledError`.
- **`__all__` only in the public API surfaces** (`__init__.py`,
  `client/__init__.py`).
- **Import order** stdlib → third-party → local (ruff-enforced).
- Run modules with `uv run python ...`, never bare `python`.

---

## Versioning & Compatibility

- **The public API is a contract.** What top-level `__init__` exports — including
  the re-exported strands-compose types — is what consumers depend on. Adding is
  cheap; removing or changing shape is a breaking change.
- **SemVer, tracking strands-compose in lockstep.** The adapter's version moves
  with the strands-compose contract it targets. When upstream makes a breaking
  change, this package makes a corresponding breaking release rather than
  shimming — the deliberate coupling is the compatibility policy.

---

## Adding to the Project — Checklist

1. **Which side?** Server, client, shared types/media, or CLI. Unsure →
   `references/project-map.md`.
2. **Read a sibling first** and mirror its shape, docstrings, and error style.
3. **Check strands-compose first** — import from the top level; keep the two
   sanctioned deep imports inside `session.py`.
4. **New media format?** One `MediaFormatSpec` entry in the registry.
5. **New exception?** Subclass `AgentCoreClientError`, add to the error map,
   export from both public surfaces.
6. **New CLI command?** New `cmd_<name>` module, wired into the parser; use
   `CLIError` for user-facing failures.
7. **Touching the entrypoint?** Preserve single-flight (the busy-check → lock
   acquire has no `await` between it) and structured task lifetimes.
8. **Verify** before declaring done.

---

## Verify

Run from the repository root:

```bash
uv run just check    # ruff format-check + ruff lint + ty type-check + bandit
uv run just test     # pytest suite (see the library-testing skill for the gate)
```

`just check` is the gate; it must pass before a change is done. If lint fails,
run `uv run just format` first, then re-run. Do not start the app server to
verify — rely on `check` and `test`.

---

## Things NOT to Do

- Don't re-implement what strands-compose or strands provides.
- Don't blur the config/session boundary — no live objects built in the factory
  or lifespan, and no re-parsing YAML per request.
- Don't replace a cached session without `close_session` — a delegated agent's
  MCP subprocess would linger until an arbitrary cyclic-GC pass. (Process exit
  needs no teardown; the subprocess dies with the parent.)
- Don't add concurrent-invocation support or multi-tenant concurrency — the
  single-flight model is deliberate.
- Don't wrap, subclass, or re-version strands-compose types, or add compatibility
  shims for upstream changes — fix in lockstep instead.
- Don't duck-type (`getattr`/`hasattr` probing) or re-validate what a pinned type
  already guarantees.
- Don't hand-roll task/thread/queue plumbing the stdlib provides
  (`TaskGroup`, `asyncio.timeout`, `asyncio.to_thread`) — **except** the
  async-generator entrypoint, which uses an explicit `create_task` + `try/finally`
  on purpose (yielding across a `TaskGroup`/`timeout` is unsafe; see
  *Async & Concurrency*).
- Don't wrap `resolve_session` / `close_session` in `to_thread` — the platform
  already isolates the entrypoint from `/ping` (see *Async & Concurrency*).
- Don't buffer the event stream unboundedly, or swallow `CancelledError`.
- Don't mix server and client concerns, or add format tables outside the registry.
- Don't emit an error event that diverges from the upstream error schema
  (`data` must use `text` + `exception_type`); don't invent an adapter-only
  `code` field.
- Don't log payload contents, media bytes, or secrets; don't `print()` for
  diagnostics or use f-strings in log calls.
- Don't use `Optional`/`Union`/`List`/`Dict`, leave a signature untyped, or
  shadow a builtin.
- Don't add `__all__` outside the public API surfaces.
- Don't hardcode secrets; no `eval`/`exec`, `pickle` on untrusted data, or
  `subprocess(shell=True)`.
- Don't leave broken or commented-out code; comments explain **what** and **why**,
  never **when** or **how it changed**.
