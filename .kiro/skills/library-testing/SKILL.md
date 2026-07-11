---
name: library-testing
description: Write, repair, and reason about tests for strands-compose-agentcore in tests/. Use whenever adding, fixing, or reviewing tests, or deciding what to test for a change. Defines what is worth testing, what is not, and how. Library tests only; not examples or docs prose.
metadata:
  area: testing
  stack: pytest,pytest-asyncio,pytest-mock,starlette-testclient,httpx,hypothesis
---

# Library Testing

The testing doctrine for **strands-compose-agentcore**
(`src/strands_compose_agentcore/`). It defines **what is worth testing, what is
not, and how**, so the suite stays small, fast, trustworthy, and cheap to live
with. It describes principles and shapes, not a file list -- modules come and
go, the doctrine stays.

One sentence to internalise: **a test exists to catch a real regression in
behaviour, contract, or wiring -- never to mirror the code, freeze its wording,
or re-test strands-compose.** If a test can break when nothing a caller depends
on changed, it is a liability, not an asset.

This package is a **thin deployment adapter**: it bridges strands-compose YAML
configs to AWS Bedrock AgentCore Runtime via SSE streaming, multimodal payload
parsing, and a client trio. That single fact decides everything below. We do not
own agent resolution, event streaming infrastructure, model providers, or MCP
lifecycle -- strands-compose owns all of those. We test **our adapter layer**:
that the app factory wires correctly, that payloads parse and reject per
contract, that sessions resolve and cache, that clients assemble and stream, and
that our error boundaries hold.

Read `references/test-patterns.md` for concrete, copy-paste templates (owned
fakes, ASGI test client setup, payload builders, session test, streaming test,
client patterns). **This file is the law; that file is the toolbox** -- load the
toolbox only when actually writing a test.

---

## Core Principles -- NON-NEGOTIABLE

1. **Test behaviour, contracts, and wiring -- never implementation.** Assert on
   what a caller observes: the yielded event stream, the parsed `AgentInput`
   shape, the raised exception *type*, the invocation body shape, the session
   caching decision. Never on private methods, private attributes, mock call
   counts/order, log lines, or human-readable messages.
2. **Never mock what we don't own.** strands-compose (`load_session`,
   `resolve_infra`, `EventQueue`, `StreamEvent`), boto3, httpx, and starlette
   internals are off-limits as mock targets in their own right. Substitute a
   fake at **our own seam** (see Mocking Policy). Hand-built `MagicMock` events
   or agents are forbidden.
3. **Confidence per line is the metric.** Optimise for the most regressions
   caught per test maintained -- not coverage percentage, not test count. A
   smaller suite people trust beats a large one they ignore.
4. **A green suite means "safe to ship"; a red test means "something real
   broke."** Anything that fails for innocuous reasons (a rename, a reorder, a
   reworded log message) gets fixed or deleted, not tolerated.
5. **Determinism is mandatory.** No real network, no real model calls, no MCP
   subprocesses, no wall-clock waits, no `sleep`, no shared mutable state, no
   ordering assumptions. Flaky is treated as broken.
6. **Tests are read more than written -- favour DAMP over DRY.** Each test reads
   top-to-bottom as a small story: arrange inputs, drive the seam, assert the
   observable outcome. Clarity beats cleverness and reuse.
7. **Smallest reasonable test, at the lowest layer that can prove the rule.**
   Pure transform -> a unit test. Wiring -> a session/app test. End-to-end shape
   -> one integration test. Cover a rule once.

---

## The Shape -- What to Test (and how much)

We are an **integration-weighted suite with a fast unit core**. The adapter is
mostly glue, so integration-style tests through the ASGI app and through client
public methods catch the most real bugs. Weight effort in this order:

### Server side (the core -- most tests)
- **Payload parsing (fast, no network).** Good payloads parse to the correct
  `AgentInput` shape; bad payloads raise `MultimodalPayloadError` with the right
  type. Cover: string prompts, single blocks, multi-block lists, media decoding,
  reply blocks, size/count limits, mixed-block rejection. Assert the decoded
  *value* (type + structure), never internal function calls.
- **Session lifecycle and wiring.** `resolve_session` produces a `SessionState`
  with a live `EventQueue` and `ResolvedConfig`. `run_entry_agent` places events
  on the queue and closes it on success, timeout, and error. Test through the
  public functions, with strands-compose faked at our seam.
- **App entrypoint (integration).** Drive `/invocations` via Starlette
  `TestClient` or httpx `ASGITransport`. Assert: correct event stream shape for
  a happy invocation, error event for bad payload, error event for busy
  rejection, session caching (same session ID reuses `SessionState`), new session
  ID triggers re-resolution.
- **Invocation locking and concurrency.** The lock prevents parallel runs; a
  second request while busy yields an error event. Test by holding the lock,
  sending a second request, asserting the rejection event.

### Client side
- **Body assembly (`build_invocation_body`).** String, single block, list of
  blocks all produce the correct `{"prompt": ...}` shape. Invalid inputs raise
  `ValueError`.
- **SSE parsing (`parse_sse_line`).** Valid `data: {...}` lines produce a
  `StreamEvent`; blank/noise lines return `None`. Never assert on the exact
  `StreamEvent` fields beyond what the contract defines.
- **Error translation (`translate_error`).** Each AWS error code maps to the
  correct exception subclass. Unknown codes fall to the base class.
- **Client invoke contract.** `LocalClient.invoke` and `AsyncLocalClient.invoke`
  yield `StreamEvent` objects from a mocked HTTP response. `AgentCoreClient`
  yields events from a mocked boto3 response. Fake at the transport seam
  (urllib response / httpx stream / boto3 client), not inside the clients.

### Media and types
- **Media builders.** `text()`, `image()`, `document()`, `reply()` produce the
  correct typed dict shape. Format inference from extensions works for all
  registered formats. Missing format on raw bytes raises `ValueError`.
  Non-existent paths raise `FileNotFoundError`.
- **Format registry invariants (property tests).** Every `MediaFormatSpec` has a
  non-empty format, a valid category, at least one extension starting with `.`,
  and a non-empty MIME type. `IMAGE_FORMATS` and `DOCUMENT_FORMATS` are disjoint
  and their union covers all entries.
- **Session ID validation.** `validate_session_id` accepts `None` and valid
  lengths, rejects too-short and too-long strings with `ValueError`.

### CLI (thin -- one test per command path)
- `cmd_dev` raises `CLIError` for missing config or port-in-use.
- `cmd_client` dispatches to the right client type.
- `main()` catches `CLIError` and exits with the right code.

---

## What We DO NOT Test

This list is as important as the one above. Do not write tests that assert on:

- **Private methods or attributes.** `_decode_block`, `_invoke_sync`,
  `_producer`, `_port_in_use` internals -- drive the public seam and observe
  the result.
- **Mock interactions.** `mock.assert_called_once_with(...)`, call order/counts
  on our own functions. These freeze implementation, not behaviour.
- **Log output, warning text, error/exception *messages*, human copy.** Only
  the error *type* and *category* are contract. `match=` in `pytest.raises`
  targets a stable token (a field name, a format string), never a full sentence.
- **strands-compose behaviour.** `load_session` producing agents, `EventQueue`
  mechanics, `StreamEvent.from_dict` round-trips, `AnsiRenderer` output. Trust
  your dependencies.
- **boto3/botocore behaviour.** `ClientError` structure, session creation,
  region resolution. Trust the SDK.
- **Trivia and tautologies.** `TextBlock` being a `TypedDict`, `RetryConfig`
  defaults, `__all__` membership, constants, dataclass field assignment,
  `__repr__`.
- **Exact event counts or sequences everywhere.** Assert the specific event
  you care about (e.g. the error event, the session_start, the session_end) --
  not `len(events) == 7`.
- **Anything that forces a test edit after a behaviour-preserving refactor.**
  If moving code between private helpers breaks a test, the test was wrong.

---

## Folder Structure -- MANDATED

`tests/` mirrors the **adapter's concerns** (not the source file tree). Keep it
shallow and predictable; a reader finds the test for a concern without matching
filenames.

```
tests/
├── conftest.py            # root: markers, shared infrastructure fixtures, app builder
├── factories.py           # payload builders, config builders, event builders (defaults + overrides)
├── fakes/                 # hand-written fakes for owned seams
│   └── compose.py             # FakeResolvedConfig, FakeEntry, FakeEventQueue, fake_resolve_session
├── server/                # server-side concerns
│   ├── test_payload.py        # payload parsing: valid/invalid, media decoding, limits
│   ├── test_session.py        # resolve_session wiring, run_entry_agent (timeout, error, success)
│   └── test_app.py            # /invocations integration: streaming, caching, locking, busy rejection
├── client/                # client-side concerns
│   ├── test_body.py           # build_invocation_body shape
│   ├── test_sse.py            # parse_sse_line parsing
│   ├── test_errors.py         # translate_error mapping
│   ├── test_local.py          # LocalClient + AsyncLocalClient invoke contract
│   └── test_agentcore.py      # AgentCoreClient invoke + stop_session contract
├── media/                 # media builders + format registry
│   ├── test_builders.py       # text(), image(), document(), reply() shape + errors
│   └── test_formats.py        # property tests: registry invariants
├── cli/                   # CLI dispatch and error handling
│   └── test_commands.py       # cmd_dev, cmd_client, main() dispatch
├── contract/              # deliberate shape guards
│   └── test_wire_shape.py     # one snapshot: invocation body keys, error event shape, content block shapes
└── utils/                 # internal utility behaviour
    └── test_validation.py     # validate_session_id, error_event builder
```

Rules:
- **Mirror the concern, not the file.** `server/test_payload.py` covers all
  payload logic regardless of internal helpers. Do not create one test file per
  source file.
- **Shared infrastructure in `conftest.py`; shared object construction in
  `factories.py`; shared fakes in `fakes/`.** Nothing else is shared.
- New concern -> the matching folder. Pure logic -> `utils/` or `media/`.
- `server/test_app.py` tests carry the `integration` marker; everything else is
  the fast tier.

---

## Mocking Policy -- Fake at Our Seam, Never Mock strands-compose

Our external dependencies are **strands-compose** (agent resolution, event
streaming, config parsing), **boto3** (AWS API calls), **httpx** (async HTTP),
and **urllib** (sync HTTP). Everything else is our own code and must run for
real.

### The owned seams (where to substitute)

| Seam | What to fake | How |
|------|-------------|-----|
| `resolve_session` in `app.py` | Session resolution | Patch `strands_compose_agentcore.app.resolve_session` to return a `FakeSessionState` |
| `load_session` in `session.py` | Agent building | Patch `strands_compose_agentcore.session.load_session` to return a `FakeResolvedConfig` |
| `resolved.entry.invoke_async` | Agent execution | Use a `FakeEntry` whose `invoke_async` returns immediately or raises |
| `EventQueue` drain | Event stream | Use a pre-loaded `FakeEventQueue` that yields scripted events |
| boto3 client method | AWS call | Patch `self._client.invoke_agent_runtime` or `stop_runtime_session` to return canned responses |
| urllib `urlopen` | HTTP transport | Patch `urllib.request.urlopen` to return a fake response with SSE lines |
| httpx stream | HTTP transport | Use `httpx.MockTransport` or patch `self._http.stream` |

### Rules

- **Never mock strands-compose or strands internals.** `EventQueue.put_event`,
  `StreamEvent.__init__`, `load_config`, `AppConfig.model_validate` -- off-limits.
  Fake at our resolution/invocation seam.
- **Prefer fakes over `Mock`.** A fake is a real object with a working
  implementation that survives dependency upgrades. A `FakeEntry` with an
  `invoke_async` coroutine is better than `MagicMock(spec=Agent)`. Reserve
  `unittest.mock` for forcing hard-to-produce conditions (timeouts, transport
  errors), always with `spec_set=`.
- **Never mock our own code under test.** Use the real `parse_payload`, real
  `build_invocation_body`, real `validate_session_id`. Mocking what you're
  testing tests nothing.
- **Patch where used, not where defined.** Patch
  `strands_compose_agentcore.session.load_session`, not
  `strands_compose.config.loaders.loaders.load_session`.

---

## Test Data -- Builders, Not Fixture Sprawl

- **Use builder functions in `factories.py`** that construct payloads, configs,
  and events with sensible defaults and accept overrides for only the fields the
  test cares about: `payload(prompt="Hello")`, `image_payload(format="png")`,
  `error_event(message="timeout")`. This keeps each test's relevant inputs
  visible.
- **Avoid the giant conftest fixture web.** A fixture is justified only for
  genuine shared infrastructure (the ASGI client, the patched session seam). Not
  for business objects.
- **DAMP, not DRY, inside a test.** Inline the arrange step that tells the
  story. Don't hide it behind loops, multi-level helpers, or parametrize-abuse
  the reader must chase. Light duplication across tests is fine and expected.

---

## Property-Based Testing (Hypothesis) -- Targeted

Use where a rule must hold across a domain of inputs:

- **Format registry:** every entry has valid category, non-empty extensions with
  leading `.`, image/document sets are disjoint, union covers all entries.
- **Payload size rejection:** any payload above `max_payload_bytes` is rejected
  regardless of content shape.
- **Session ID validation:** any string outside 33-256 chars is rejected; any
  string within bounds is accepted; `None` is always accepted.
- **Base64 round-trip:** encoding then decoding media bytes is identity.
- **Body assembly:** any valid `AgentInput` produces a dict with a `"prompt"`
  key whose value is a string or non-empty list.

Keep generators tight. Assert the **invariant**, not a re-computation.

---

## Coverage and Mutation -- Signal, Not Theatre

- **Coverage is a floor (>= 90%) and a gap-finder, never a goal.** A high
  number with weak assertions is false confidence. Tests that execute lines
  without asserting are forbidden. Do not chase 100% and do not add a test
  purely to move the number.
- **Assertion quality is the real signal.** For the modules that matter most
  (`payload.py`, `session.py`, `client/utils.py`, `media.py`), validate the
  suite with mutation testing periodically. Treat surviving mutants as the
  to-do list.

---

## Conventions

- **`from __future__ import annotations`** at the top of every test module.
- **Name states behaviour + expectation:**
  `test_payload_rejects_oversized_media_with_error`,
  `test_session_caches_state_for_same_id`,
  not `test_parse` or `test_session`.
- **Arrange-Act-Assert**, visibly separated. One logical behaviour per test; one
  reason to fail.
- **`pytest.raises` asserts the type; `match=` targets a stable token** (a field
  name, a limit number), never a full sentence.
- **Parametrize** equivalent cases (all supported image formats, all error codes)
  instead of copy-pasting near-identical bodies.
- **Async:** `pytest-asyncio` auto mode is on. Mark async tests and use async
  fakes. Never block the loop or sleep.
- Typed signatures; keep tests readable, not ceremony-heavy.
- **Run with `uv run just test`** (never bare `pytest`); use
  `uv run pytest <path>` for fast local iteration on one file.

---

## Adding or Repairing a Test -- Checklist

1. **Name the behaviour** you're protecting in one sentence. If you can't, you
   probably shouldn't write the test.
2. **Pick the lowest layer** that proves it: payload -> `server/test_payload.py`;
   session wiring -> `server/test_session.py`; end-to-end -> `server/test_app.py`;
   client shape -> `client/`; media -> `media/`; utils -> `utils/`.
3. **Read a sibling test first** and mirror its shape, naming, and factories.
4. **Use real code through the public seam; fake only strands-compose at our
   resolution/invocation seam.**
5. **Assert on type / shape / yielded event / raised exception type -- never on
   text, private members, or mock calls.**
6. **When a test breaks after a refactor:** first ask *did behaviour change?* If
   no, the test was over-specified -- fix or delete it. If yes, the test did its
   job -- update the expectation.
7. **Verify** before declaring done: `uv run just check` then `uv run just test`.

---

## Anti-Patterns -- Do NOT

- Call private helpers directly (`_decode_block`, `_invoke_sync`) or read private
  state to make an assertion; drive the public seam.
- Fabricate strands-compose events with `MagicMock` / `SimpleNamespace`, or patch
  `EventQueue.__init__` -- use a pre-loaded fake or a real `StreamEvent`.
- Mock strands-compose, boto3, httpx, or starlette internals directly.
- Mock our own code under test (`parse_payload`, `build_invocation_body`).
- Assert on log messages, exception text, or response wording (type only).
- Assert `len(events) == N` or a full event sequence outside the one contract
  snapshot.
- Test `TypedDict` field assignment, dataclass defaults, `__all__` membership,
  or constant values.
- Build one test file per source file, or split one concern across two files.
- Add a test that only raises the coverage number, or a test with no assertion.
- Hide a test's arrange step behind clever helpers, loops, or `setUp` magic.
- Use `sleep`, real clocks, real network, real model calls, shared state.
- Leave a flaky test "for later" -- quarantine and fix, or delete.
