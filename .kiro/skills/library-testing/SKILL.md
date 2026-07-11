---
name: library-testing
description: Write, repair, and reason about tests for strands-compose-agentcore in tests/. Use whenever adding, fixing, or reviewing tests, or deciding what to test for a change. Defines what is worth testing, what is not, and how. Library tests only; not examples or docs prose.
metadata:
  area: testing
  stack: pytest,pytest-asyncio,pytest-mock,starlette,httpx,botocore-stubber
---

# Library Testing

The testing doctrine for **strands-compose-agentcore**
(`src/strands_compose_agentcore/`). It defines **what is worth testing, what is
not, and how**, so the suite stays small, fast, trustworthy, and cheap to live
with. It states principles and shapes, not a file list — modules come and go,
the doctrine stays.

One sentence to internalise: **a test exists to catch a real regression in
behaviour, contract, or wiring — never to mirror the code, freeze its wording,
or re-test strands-compose.** If a test can break when nothing a caller depends
on changed, it is a liability, not an asset.

## What this package actually is (and why it decides everything)

This package is a **thin deployment adapter with a live network surface**. Three
facts drive the whole doctrine:

1. **It streams.** The server turns one HTTP POST into an ordered sequence of
   SSE `StreamEvent`s. Event *ordering and lifecycle* is the product, not a side
   effect.
2. **It fails over a network.** Its real value is behaving correctly when things
   go wrong — bad payloads, timeouts, throttling, dropped connections, a busy
   session, garbage on the wire. **The failure paths are the feature.**
3. **It has a two-sided wire contract.** The client (`build_invocation_body`,
   the `media` builders) and the server (`parse_payload`) must agree on
   `{"prompt": ...}`, and both sides must agree with the SSE `StreamEvent` shape
   (`parse_sse_line`). Drift here is the single most likely real bug.

We do **not** own agent resolution, event-queue mechanics, model providers, or
MCP lifecycle — strands-compose owns those. We test **our adapter layer**: that
payloads parse and reject per contract, that the stream carries the right
lifecycle, that sessions resolve/cache/lock correctly, that failures degrade to
a clean error event, that clients assemble/parse/translate correctly, and that
the two ends of the wire never drift.

Read `references/test-patterns.md` for concrete, copy-paste templates. **This
file is the law; that file is the toolbox** — load the toolbox only when
actually writing a test.

---

## Core Principles — NON-NEGOTIABLE

1. **Test behaviour, contracts, and wiring — never implementation.** Assert on
   what a caller observes: the yielded event stream and its *order*, the parsed
   `AgentInput` shape, the raised exception *type*, the invocation body shape,
   the session caching/locking decision. Never on private helpers
   (`_decode_block`, `_invoke_sync`, `_producer`), private attributes, mock call
   counts/order, log lines, or human-readable messages.
2. **Fake at our own seam; never mock what we don't own.** strands-compose
   (`load_session`, `resolve_infra`, `EventQueue`, `StreamEvent`,
   `build_manifest`), boto3/botocore, httpx, urllib, and Starlette internals are
   off-limits as mock targets in their own right. Substitute a fake at **our**
   boundary, or use the vendor's own test seam (`botocore.Stubber`,
   `httpx.MockTransport`) — see Mocking Policy. Hand-built `MagicMock` events or
   agents are forbidden.
3. **Confidence per line is the metric.** Optimise for the most regressions
   caught per test maintained — not coverage percentage, not test count. A
   smaller suite people trust beats a large one they ignore.
4. **A green suite means "safe to ship"; a red test means "something real
   broke."** Anything that fails for innocuous reasons (a rename, a reorder, a
   reworded message) gets fixed or deleted, not tolerated.
5. **Determinism is mandatory.** No real network, no real model calls, no MCP
   subprocesses, no wall-clock waits, no `sleep`, no shared mutable state, no
   ordering assumptions about incidental events. Control time and concurrency
   with gates (an `asyncio.Event`), not delays. Flaky is treated as broken.
6. **Tests are read more than written — favour DAMP over DRY.** Each test reads
   top-to-bottom as a small story: arrange inputs, drive the seam, assert the
   observable outcome. Clarity beats cleverness and reuse.
7. **Smallest reasonable test, at the lowest layer that can prove the rule.**
   Pure transform → a unit test. Wiring → a session/app test. End-to-end shape →
   one pipeline test. Cover a rule once.

---

## The Shape — What to Test (and how much)

We are an **integration-weighted suite with a fast unit core** (the testing
"trophy", correct for glue that mostly wires other systems together). The adapter
is mostly glue, so tests through the ASGI app and through client public methods
catch the most real bugs; a fast pure-function core underpins them. Weight effort
in this order, but let the code under test decide, not dogma.

### 1. The wire contract — two-sided (highest value, test first)
The client and server must never drift. Treat this as a first-class concern.
- **Payload parsing (server, `parse_payload`).** Good payloads parse to the
  correct `AgentInput` shape; bad payloads raise `MultimodalPayloadError`. Cover:
  string prompts, single block, multi-block lists, media base64→bytes decoding,
  reply→`interruptResponse` conversion, size/count limits, mixed-reply rejection,
  unsupported formats. Assert the decoded *value* (type + structure), or the
  exception *type* (see Error Assertions).
- **Body assembly (client, `build_invocation_body`).** `str`, single block, list
  of blocks each produce the correct `{"prompt": ...}` shape; invalid input
  raises `ValueError`.
- **Round-trip (the drift guard).** A block built by `text()`/`image()`/
  `document()`/`reply()` → `build_invocation_body` → `parse_payload` yields the
  expected Strands runtime shape. This is the test that actually catches
  client/server drift; it is worth several isolated tests on either side.
- **SSE shape (`parse_sse_line`).** A `data: {...}` line round-trips to a
  `StreamEvent`; blank/noise/`: comment`/non-JSON lines return `None`.

### 2. Streaming lifecycle and failure paths (the core — most tests)
The adapter is defined by its event stream and how it degrades. Drive the ASGI
app (`create_app`) via Starlette `TestClient` / httpx `ASGITransport`, and drive
`run_entry_agent` directly, faking strands-compose at our seam.
- **Happy path stream.** One invocation yields a lifecycle that *begins with a
  `session_start` and ends cleanly* (queue drained to the close sentinel). Assert
  the meaningful ordered subsequence, not incidental token counts.
- **Failure paths — each degrades to exactly one error event, no crash, stream
  still closes.** This is where the real bugs live. Cover:
  - invalid payload → error event, session never resolved;
  - invalid `session_id` → error event;
  - `resolve_session` raises → error event, app stays up;
  - busy session (invocation lock held) → rejection error event;
  - entry-agent timeout (`invocation_timeout`) → error event then close;
  - entry-agent raises → error event then close;
  - consumer disconnect / generator cancellation mid-stream → the run task is
    cancelled and awaited, nothing leaks.
- **Session caching and locking (wiring).** Same `session_id` reuses the cached
  `SessionState`; a new `session_id` triggers re-resolution; a second request
  while the lock is held is rejected. Test by holding the real lock, not by
  inspecting internals.

### 3. Client transport behaviour
Fake at the transport seam (`botocore.Stubber`, `httpx.MockTransport`, a fake
`urlopen` response) — never inside the clients.
- **Invoke streaming.** `LocalClient`, `AsyncLocalClient`, and `AgentCoreClient`
  each yield `StreamEvent`s from a scripted transport response; `raw_output=True`
  yields the filtered raw lines.
- **Error translation (`translate_error`).** Each AWS error code maps to the
  correct `AgentCoreClientError` subclass; unknown codes fall to the base class.
- **Transport failure.** `urllib` `URLError` and `httpx.ConnectError` become
  `ClientConnectionError`; a throttled `AgentCoreClient` retries per `RetryConfig`
  and then raises `ThrottledError`. Drive retry deterministically (patch the
  sleep/seam, never wait).

### 4. Media builders and format registry (fast unit)
- **Builders.** `text()`, `image()`, `document()`, `reply()` produce the correct
  typed shape. Format inference from extensions works; missing format on raw
  bytes raises `ValueError`; a non-existent path raises `FileNotFoundError`;
  `document()` name defaulting appends a suffix, explicit `name=` does not.
- **Registry invariants.** Prefer example-based checks that `IMAGE_FORMATS` and
  `DOCUMENT_FORMATS` are disjoint and their union covers `MEDIA_FORMATS`. (See
  Property-Based Testing for when to generalise — and when *not* to.)

### 5. Utilities and CLI (thin — one test per path)
- `validate_session_id` accepts `None` and in-range lengths, rejects
  out-of-range with `ValueError`.
- `error_event` builds a `StreamEvent` with `type="error"`.
- CLI: `cmd_dev` raises `CLIError` for missing config / port-in-use; `cmd_client`
  dispatches to the right client; `main()` catches `CLIError` and exits with the
  right code.

---

## Failure-Injection Doctrine — an adapter is defined by how it fails

For a network/streaming adapter, the ugly paths carry more regression risk than
the happy path. Give them first-class coverage and make them deterministic:

- **Every failure has one observable contract: a single `type="error"`
  `StreamEvent`, no unhandled exception escaping the entrypoint, and the stream
  still closing.** Assert those three, not the message text.
- **Inject faults at our seam, not with real failures.** A `FakeEntry` that
  raises, that never completes (for timeout/cancellation), or that gates on an
  `asyncio.Event` you control. A transport double that yields truncated or
  garbage SSE lines. A `botocore.Stubber` primed with a `ClientError`.
- **Timeouts and cancellation are tested with gates, not clocks.** To prove the
  timeout branch, pair a `FakeEntry` that awaits an event you never set with a
  tiny `invocation_timeout`; to prove cancellation, break the consumer's drain
  loop and assert the run task was cancelled. Never `sleep` to "let it finish".
- **Garbage on the wire is normal.** `parse_sse_line` must swallow blanks,
  keepalives, comments, and non-JSON and return `None`; the client invoke loop
  must skip them without raising.

---

## Streaming Assertions — order is contract, counts are not

Event order *is* our contract, so it is fair game to assert on — with care:

- **DO** assert the meaningful ordered subsequence: a `session_start` opens the
  stream; an error event appears where expected; the stream terminates on the
  close sentinel (`EventQueue.get()` returning `None`).
- **DO NOT** assert exact counts of incidental events (`len(events) == 7`), the
  number of token deltas, or the full verbatim event list. Those change when
  strands-compose changes and are not our contract.
- Pin the *shape* of the events we author (the error event, the wire keys) once,
  in the contract snapshot — not in every streaming test.

---

## Error Assertions — type is contract, prose is not

- **Assert the exception *type*.** `pytest.raises(MultimodalPayloadError)`,
  `pytest.raises(ClientConnectionError)`, `isinstance(exc, ThrottledError)`.
- **`match=` may target only a stable structural token that is itself part of a
  contract** — a wire/config field name (`prompt`, `image`, `format`, `base64`,
  `name`) or a limit-parameter name (`max_media_bytes`, `max_media_blocks`,
  `max_payload_bytes`). **Never match a prose sentence** ("must be a string",
  "not supported"): rewording the message must never break a test.
- **When one exception type covers many rejection reasons** (as
  `MultimodalPayloadError` does), the *contract* is "rejected with this type" —
  the specific reason is generally not contract, so prefer asserting the type
  plus the offending input. If reason-level assertions ever become genuinely
  important, add a machine-readable `reason`/`code` attribute to the exception
  in the source and assert on that — do **not** reach for message matching.

---

## Folder Structure — suggested, not mandated

`tests/` should mirror the **adapter's concerns**, stay shallow, and let a reader
find the test for a concern without matching source filenames. For a package this
small, a rigid deep tree is over-engineering; the layout below is a *suggestion*,
and a flatter arrangement is acceptable as long as concerns are not scattered.

```
tests/
├── conftest.py            # markers + shared infra fixtures (app builder, faked model seam)
├── factories.py           # payload/body builders, event builders (defaults + overrides)
├── fakes/                 # hand-written fakes for owned seams
│   ├── compose.py         # FakeEntry, FakeResolvedConfig, session helpers
│   └── transport.py       # fake urlopen response, httpx MockTransport, Stubber helpers
├── server/                # payload parsing, session lifecycle, app streaming + faults + locking
├── client/                # body assembly, sse parsing, error translation, local + agentcore invoke
├── media/                 # builders + format registry
├── cli/                   # dispatch + error handling
└── contract/              # wire round-trip + one shape snapshot (body keys, error event, blocks)
```

Guidelines (not rules):
- **Mirror the concern, not the file.** One file may cover all payload logic
  regardless of internal helpers. Do not create one test file per source file.
- Shared infrastructure → `conftest.py`; shared construction → `factories.py`;
  shared fakes → `fakes/`. Nothing else is shared.
- App-level streaming/fault tests carry the `integration` marker; everything else
  is the fast tier.

---

## Mocking Policy — Fake at Our Seam

Our external dependencies are **strands-compose** (agent resolution, event
streaming, config parsing, manifest), **boto3/botocore** (AWS), **httpx** (async
HTTP), and **urllib** (sync HTTP). Everything else is our own code and runs for
real.

### Two fidelity levels

**Adapter-seam fakes (fast, most tests).** Fake strands-compose at *our* module
boundary and drive our wiring:

| Seam (patch where used) | Fake with | Proves |
|---|---|---|
| `strands_compose_agentcore.app.resolve_session` | `FakeSessionState` | app streaming, caching, locking, fault handling |
| `strands_compose_agentcore.session.load_session` | returns `FakeResolvedConfig` | `resolve_session` wiring |
| `resolved.entry.invoke_async` | `FakeEntry` (result / raise / gate / never-complete) | `run_entry_agent` success, error, timeout, cancel |
| `EventQueue` | **use the real one** via `wire_event_queue()` | event drain + close, cheaply and deterministically |

**Pipeline integration (a few tests, higher fidelity).** For end-to-end
`/invocations` behaviour, prefer building a real app from a tiny real YAML with
only the **model provider** faked at strands-compose's resolver seam
(`resolve_model` → a fake model that emits scripted events — confirm the current
seam name via the `library-development` skill / project map). This runs real
`load_session`, real `EventQueue`, and real `build_manifest`, so you never patch
`build_manifest` and you catch upstream drift. Patching `build_manifest` at our
app seam is a fallback for pure adapter-seam tests only, and is a smell if it
becomes the default.

### Rules

- **Never mock strands-compose or strands internals** (`EventQueue.put_event`,
  `StreamEvent.__init__`, `load_config`, `build_manifest`). Fake at our
  resolution/invocation seam, or use a real object.
- **Prefer fakes over `Mock`.** A `FakeEntry` with a real `invoke_async`
  coroutine beats `MagicMock(spec=Agent)`; it survives dependency upgrades and
  reads clearly. Reserve `unittest.mock` for forcing hard-to-produce conditions,
  always with `spec_set=`.
- **Use the vendor's own test seam for transport.** `botocore.Stubber` for the
  `AgentCoreClient` boto3 calls (it validates the request shape against the real
  API, so a wrong parameter fails loudly — a patched `MagicMock` would not);
  `httpx.MockTransport` for `AsyncLocalClient`; a fake response object for
  `LocalClient`'s `urlopen`. Do **not** patch boto3 client methods with
  `MagicMock`.
- **Never mock our own code under test.** Real `parse_payload`, real
  `build_invocation_body`, real `translate_error`, real `validate_session_id`.
- **Patch where used, not where defined.** Patch
  `strands_compose_agentcore.session.load_session`, not the upstream module.

---

## Test Data — Builders, Not Fixture Sprawl

- **Use builder functions in `factories.py`** with sensible defaults and
  targeted overrides: `payload(prompt="Hi")`, `image_payload(format="png")`,
  `error_stream_event(...)`. Keep each test's relevant inputs visible.
- **Avoid the giant conftest fixture web.** A fixture is justified only for
  genuine shared infrastructure (the ASGI client, the faked model seam), never
  for business objects.
- **DAMP, not DRY, inside a test.** Inline the arrange step that tells the story.
  Light duplication across tests is fine and expected.

---

## Property-Based Testing (Hypothesis) — targeted, and only for real invariants

Property tests are valuable **only where a rule must hold across a domain of
runtime inputs**. They are *not* for re-checking hardcoded data tables or the
standard library.

Requires `hypothesis` in the dev dependency group — add it before writing these,
or skip them. They are optional; the example-based core comes first.

Good fits here:
- **Session ID validation:** any string of length 33–256 is accepted; anything
  outside is rejected; `None` is always accepted.
- **Payload size rejection:** any payload whose JSON encoding exceeds
  `max_payload_bytes` is rejected regardless of inner shape.
- **Body assembly:** any valid `AgentInput` produces a dict with a `"prompt"`
  key whose value is a `str` or a non-empty `list`.

**Not** property-test targets (these violate "don't test data/dependencies"):
- The static `MEDIA_FORMATS` table's field values — that is a data-entry check,
  not a behavioural invariant. A single example-based test that the sets are
  disjoint and cover the table is enough.
- base64 encode/decode round-trips — that tests the standard library, which we
  do not own.

Keep generators tight. Assert the **invariant**, never a re-computation of the
implementation.

---

## Coverage and Mutation — Signal, Not Theatre

- **Coverage is a floor and a gap-finder, never a goal.** The gate is **≥ 75 %**
  branch coverage — a safety net sized for glue code, not a target to chase. A
  high number with weak assertions is false confidence; tests that execute lines
  without asserting are forbidden. Do not add a test purely to move the number,
  and do not chase 100 %.
- **Mutation testing is the real quality signal** for the modules that carry
  logic (`payload.py`, `client/utils.py`, `media.py`, `session.py`). If adopted,
  add `mutmut` to the dev dependency group and a `just mutate` task; run it
  periodically and treat surviving mutants — not uncovered lines — as the to-do
  list. If the tool is not wired up, do not pretend it is: fix that first or omit
  the claim.

---

## Conventions

- **`from __future__ import annotations`** at the top of every test module.
- **Name states behaviour + expectation:**
  `test_payload_rejects_oversized_media`, `test_stream_emits_error_event_on_timeout`,
  `test_session_reuses_state_for_same_id` — not `test_parse` or `test_session`.
- **Arrange-Act-Assert**, visibly separated. One logical behaviour per test; one
  reason to fail.
- **`pytest.raises` asserts the type; `match=` only a stable token** (a field or
  limit name), never a sentence.
- **Parametrize** equivalent cases (all image formats, all AWS error codes)
  instead of copy-pasting near-identical bodies.
- **Async:** `pytest-asyncio` auto mode is on. Use async fakes and gates; never
  block the loop or sleep.
- Typed signatures; readable over ceremony.
- **Run with `uv run just test`** (never bare `pytest`); use `uv run pytest <path>`
  for fast local iteration on one file.

---

## Adding or Repairing a Test — Checklist

1. **Name the behaviour** you're protecting in one sentence. If you can't, you
   probably shouldn't write the test.
2. **Pick the lowest layer** that proves it: parsing/body → `server/`, `client/`;
   drift → `contract/`; streaming/faults/locking → `server/` (integration);
   transport → `client/`; pure logic → `media/`, `cli/`, or a util test.
3. **Read a sibling test first** and mirror its shape, naming, and factories.
4. **Use real code through the public seam; fake only strands-compose at our
   resolution/invocation seam, and transports at the vendor test seam.**
5. **Assert on type / shape / yielded-event order / raised exception type —
   never on text, private members, or mock calls.**
6. **When a test breaks after a refactor:** first ask *did behaviour change?* If
   no, the test was over-specified — fix or delete it. If yes, the test did its
   job — update the expectation.
7. **Verify** before declaring done: `uv run just check` then `uv run just test`.

---

## Anti-Patterns — Do NOT

- Call private helpers (`_decode_block`, `_invoke_sync`, `_producer`) or read
  private state to make an assertion; drive the public seam.
- Fabricate strands-compose events or agents with `MagicMock` / `SimpleNamespace`,
  or patch `EventQueue.__init__` — use a real `StreamEvent`/`EventQueue` or a
  pre-loaded fake.
- Mock strands-compose, boto3 client methods, httpx, or Starlette internals
  directly — fake at our seam or use `botocore.Stubber` / `httpx.MockTransport`.
- Mock our own code under test (`parse_payload`, `build_invocation_body`).
- Assert on log messages, exception prose, or response wording (type + stable
  token only).
- Assert `len(events) == N`, token-delta counts, or a full verbatim event
  sequence. (Ordered *subsequence* of the lifecycle is fine and expected.)
- Property-test the `MEDIA_FORMATS` table or base64 round-trips.
- Test `TypedDict` field assignment, dataclass defaults, `__all__` membership,
  or constants.
- Build one test file per source file, or split one concern across two files.
- Add a test that only raises the coverage number, or a test with no assertion.
- Use `sleep`, real clocks, real network, or real model calls to control timing —
  gate on an `asyncio.Event` instead.
- Patch `build_manifest` as the default path — prefer a real tiny config with a
  faked model seam.
- Leave a flaky test "for later" — quarantine and fix, or delete.
