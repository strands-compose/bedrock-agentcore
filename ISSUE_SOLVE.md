# Issue Resolution Plan

Each issue below is self-contained.  An agent can pick any single issue, implement the
exact changes described, run `uv run just check && uv run just test`, and open a PR.

**Rules for every change:**

- `from __future__ import annotations` at the top of every new or modified module.
- Full type hints on every function signature (parameters + return type).
- Google-style docstrings on every public class, function, and method.
- Structured logging with `%s` interpolation — never f-strings.
- Run `uv run just check && uv run just test` before committing.

---

## Issue 1 — Session ID max-length validation missing on server path

### Problem

`AgentCoreClient.invoke()` in `src/strands_compose_agentcore/client/agentcore.py`
validates both the 33-char minimum and 256-char maximum on `session_id`.
The server's `/invocations` entrypoint in `src/strands_compose_agentcore/app.py`
performs **no** validation at all on the session ID received from
`BedrockAgentCoreContext.get_session_id()`.
A malformed session ID silently passes through to `load_session()`.

### Solution

Add a private helper `_validate_session_id()` to `src/strands_compose_agentcore/session.py`
and call it from the `/invocations` entrypoint in `app.py`, right after
`session_id = BedrockAgentCoreContext.get_session_id()` and before the
concurrency guard.

#### File: `src/strands_compose_agentcore/session.py`

Add two module-level constants and one validation function **before** the
`resolve_session` function:

```python
# AgentCore session ID length constraints.
_MIN_SESSION_ID_LENGTH = 33
_MAX_SESSION_ID_LENGTH = 256


def validate_session_id(session_id: str | None) -> None:
    """Validate the AgentCore session ID length.

    Args:
        session_id: The raw session ID from the runtime header.

    Raises:
        ValueError: If the session ID is outside the 33–256 char range.
    """
    if session_id is None:
        return
    if len(session_id) < _MIN_SESSION_ID_LENGTH:
        raise ValueError(
            "session_id=<%s> is too short (%d chars). "
            "AgentCore requires at least %d characters."
            % (session_id, len(session_id), _MIN_SESSION_ID_LENGTH)
        )
    if len(session_id) > _MAX_SESSION_ID_LENGTH:
        raise ValueError(
            "session_id=<%s...> is too long (%d chars). "
            "AgentCore allows at most %d characters."
            % (session_id[:20], len(session_id), _MAX_SESSION_ID_LENGTH)
        )
```

#### File: `src/strands_compose_agentcore/app.py`

1. Update the import line to also import `validate_session_id`:

```python
from .session import SessionState, resolve_session, stream_invocation, validate_session_id
```

2. Inside the `invoke` closure, immediately after `session_id = BedrockAgentCoreContext.get_session_id()`,
   add the validation call.  On `ValueError`, yield an error event and return:

```python
        session_id = BedrockAgentCoreContext.get_session_id()

        try:
            validate_session_id(session_id)
        except ValueError as exc:
            logger.warning("session_id=<%s> | %s", session_id, exc)
            yield StreamEvent(
                type="error",
                agent_name="",
                timestamp=datetime.now(tz=timezone.utc),
                data={"message": str(exc)},
            ).asdict()
            return
```

#### Tests: `tests/test_app_invoke.py`

Add a new test class `TestInvokeSessionIdValidation` with two tests:

- `test_rejects_short_session_id` — patch `get_session_id` to return `"short"`,
  assert a single error event with `"too short"` in the message.
- `test_rejects_long_session_id` — patch `get_session_id` to return `"a" * 257`,
  assert a single error event with `"too long"` in the message.

Also add unit tests for `validate_session_id` in `tests/test_app.py`:

- `test_validate_session_id_accepts_none` — no exception.
- `test_validate_session_id_accepts_valid` — 33-char string, no exception.
- `test_validate_session_id_rejects_short` — `pytest.raises(ValueError, match="too short")`.
- `test_validate_session_id_rejects_long` — `pytest.raises(ValueError, match="too long")`.

---

## Issue 2 — Unused pytest fixtures in conftest.py

### Problem

`tests/conftest.py` defines four `@pytest.fixture()` functions
(`mock_app_config`, `mock_infra`, `mock_resolved_config`, `mock_event_queue`)
that are **never used by any test file**.
All test files call the bare `make_*()` factory functions instead.
The fixtures are dead code.

### Solution

Delete the four fixture functions from `tests/conftest.py`.  Keep only:
- `make_infra()`
- `make_app_config()`
- `make_resolved_config()`
- `empty_stream()`

Remove these exact blocks (lines 42–68 in the current file):

```python
@pytest.fixture()
def mock_app_config() -> MagicMock:
    ...

@pytest.fixture()
def mock_infra() -> MagicMock:
    ...

@pytest.fixture()
def mock_resolved_config() -> MagicMock:
    ...

@pytest.fixture()
def mock_event_queue() -> MagicMock:
    ...
```

Also remove the `import pytest` and `from strands_compose import EventQueue`
lines **only if** no remaining code in the file uses them.
Currently `empty_stream` does not use `pytest` or `EventQueue`, so both
imports can be removed.

**Verification:** run `uv run just test` — all existing tests must pass
unchanged because they call the factory functions, not the fixtures.

---

## Issue 3 — REPL creates a fresh event loop per turn

### Problem

`AgentCoreClient.repl()` in `src/strands_compose_agentcore/client/agentcore.py`
defines a `_stream` closure that calls `asyncio.run(_run())` on every user prompt.
`asyncio.run()` creates and destroys a new event loop each time.  For a REPL that
may run dozens of turns, this is wasteful and prevents any cross-turn async state
sharing.

The existing code already handles the "called from an existing async context"
case by offloading to a thread — that part is correct.  The problem is the
"no existing loop" path which also uses `asyncio.run()` per turn.

### Solution

Create a persistent event loop in a background thread at the start of `repl()`.
All turns reuse the same loop via `asyncio.run_coroutine_threadsafe()`.

Replace the `_stream` closure and the surrounding code in the `repl()` method
(keep the session ID validation above unchanged):

```python
    def repl(self, *, session_id: str | None = None) -> None:
        # ... session ID validation unchanged ...

        import threading

        loop = asyncio.new_event_loop()
        loop_thread = threading.Thread(target=loop.run_forever, daemon=True)
        loop_thread.start()

        def _stream(prompt: str, sid: str, renderer: AnsiRenderer) -> bool:
            async def _run() -> None:
                async for event in self.invoke(session_id=sid, prompt=prompt):
                    renderer.render(event)
                renderer.flush()

            future = asyncio.run_coroutine_threadsafe(_run(), loop)
            future.result()  # block the calling thread until done
            return True

        try:
            run_repl(
                banner=f"AgentCore Client \u2014 {self.agent_runtime_arn}",
                session_id=sid,
                stream_fn=_stream,
            )
        finally:
            loop.call_soon_threadsafe(loop.stop)
            loop_thread.join(timeout=5.0)
            loop.close()
```

This removes both the `asyncio.run()` per-turn call and the
`concurrent.futures.ThreadPoolExecutor(max_workers=1)` workaround.
The loop is created once, the thread runs it, and `run_coroutine_threadsafe`
schedules each turn.  On exit the loop is stopped, the thread is joined, and
the loop is closed.

#### Tests: `tests/test_client_repl.py`

The existing tests mock `client.invoke` and `input`, so they will keep
working because the async iterator is still consumed the same way.
Update `test_repl_works_from_async_context` — it should still pass because
the REPL now always creates its own loop thread rather than trying to detect
a running one.

Verify no test imports `concurrent.futures` or patches `asyncio.run` — if
any do, remove those patches since the code no longer calls `asyncio.run`.

---

## Issue 4 — Copilot instruction drift

### Problem

`.github/copilot-instructions.md` says "do not duplicate rules from AGENTS.md
here" but then immediately duplicates:

- The four `uv run just ...` commands (lines 16–19).
- Six bullet points under "Key Reminders" (lines 25–30) that repeat
  AGENTS.md rules verbatim.

### Solution

Strip copilot-instructions.md down to **only** what Copilot needs beyond
AGENTS.md: the directive to read it, the project description, and the
tables of agents/skills/instructions that are Copilot-specific config.

Replace the entire file with:

```markdown
# strands-compose-agentcore — Copilot Instructions

**Read `AGENTS.md` in the repository root** — it is the single source of truth
for all project rules, architecture, Python conventions, logging style, key APIs,
directory structure, and tooling commands.

This file provides supplementary context for Copilot.
Do not duplicate rules from `AGENTS.md` here.

## Quick Reference

This is **strands-compose-agentcore**: a deployment adapter that runs
[strands-compose](https://github.com/strands-compose/sdk-python) YAML configs
on [AWS Bedrock AgentCore Runtime](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/).

## Custom Agents

Specialized agents are defined in `.github/agents/`.
Select the right one for your task:

| Agent | Purpose | Tool Access |
|-------|---------|-------------|
| `developer` | Implement features and fix bugs | read, edit, search, execute, agent |
| `reviewer` | Review PRs for correctness and compliance | read, search, execute (read-only) |
| `tester` | Write and improve tests | read, edit, search, execute |
| `docs-writer` | Write and update documentation | read, edit, search, execute |

## Skills

Skills in `.github/skills/` are **automatically activated** when relevant:

| Skill | Triggered When |
|-------|---------------|
| `check-and-test` | Validating, linting, testing, or checking code quality |
| `strands-api-lookup` | Working with strands/strands-compose APIs, checking upstream functionality |

## Path-Specific Instructions

Targeted rules in `.github/instructions/` are applied automatically based on file paths:

| File | Applies To |
|------|-----------|
| `source.instructions.md` | `src/**/*.py` |
| `tests.instructions.md` | `tests/**/*.py` |
| `examples.instructions.md` | `examples/**/*.py`, `examples/**/*.yaml` |
| `docs.instructions.md` | `docs/**/*.md` |
```

Removed sections: **Environment** (duplicates AGENTS.md tooling commands),
**Key Reminders** (duplicates AGENTS.md "Things to Do" rules).

---

## Issue 5 — Concurrency guard TOCTOU smell

### Problem

In `src/strands_compose_agentcore/app.py` (lines 200–240), the `/invocations`
entrypoint checks `session.invocation_lock.locked()` on line 201, then
resolves the session (lines 215–232), and only then acquires the lock
with `async with session.invocation_lock:` on line 236.

The `locked()` check and the `async with` acquire are separated by 35 lines
of code including session resolution.  While `resolve_session()` is
synchronous (no `await`), the layout makes it look like there could be
an await gap — and a future refactor that adds an `await` between them
would silently break the atomicity.

`asyncio.Lock` has no `try_acquire()` method.  `lock.acquire()` always
awaits until the lock is available — it cannot reject.  So `locked()` is
the **only** way to do a non-blocking busy check in asyncio.  The pattern
is correct; the problem is purely structural.

### Solution

Reorder the invoke closure so that session resolution happens **first**,
and the `locked()` check is immediately adjacent to the `async with`
acquire — zero statements (let alone awaits) between them.

#### File: `src/strands_compose_agentcore/app.py`

Replace the block from `session_id = BedrockAgentCoreContext.get_session_id()`
through the end of the invoke closure (before `return app`) with:

```python
        session_id = BedrockAgentCoreContext.get_session_id()

        # Resolve session first (sync — no await, no context switch).
        session: SessionState | None = app.state.session
        if session is None or app.state.session_id != session_id:
            if app.state.session_id is not None:
                logger.info(
                    "session_id=<%s> | new session replaces previous session_id=<%s>",
                    session_id,
                    app.state.session_id,
                )
            session = resolve_session(
                app.state.app_config,
                app.state.infra,
                session_id,
            )
            app.state.session = session
            app.state.session_id = session_id

        # SAFETY: asyncio is single-threaded.  No await exists between
        # locked() and the async-with acquire below, so no other
        # coroutine can acquire the lock in between.
        if session.invocation_lock.locked():
            logger.warning(
                "session_id=<%s> | invocation rejected, agent already running",
                session_id,
            )
            yield StreamEvent(
                type="error",
                agent_name="",
                timestamp=datetime.now(tz=timezone.utc),
                data={"message": "agent is already running, try again later"},
            ).asdict()
            return

        task_id = app.add_async_task("invoke")
        try:
            async with session.invocation_lock:
                async for event in stream_invocation(session.resolved, session.events, prompt):
                    yield event.asdict()
        finally:
            app.complete_async_task(task_id)
```

The two changes from the current code:

1. **Session resolution moves before the busy check.**  The old order was:
   busy-check → session-resolution → acquire.  The new order is:
   session-resolution → busy-check → acquire.  This places `locked()`
   and `async with` back-to-back with nothing between them.

2. **A `# SAFETY:` comment** documents why the `locked()` + `async with`
   pair is race-free, preventing future contributors from inserting an
   `await` between them.

#### Tests: `tests/test_app_invoke.py`

The existing `test_rejects_any_request_while_busy` test (in
`TestInvokeSessionHandling`) patches `get_session_id` to return
`"different"` while the lock is held.  Under the new order, session
resolution runs before the busy check, so `resolve_session` will now
be called.  Update that test to also patch `resolve_session`:

```python
    @pytest.mark.asyncio
    async def test_rejects_any_request_while_busy(self) -> None:
        app = create_app(make_app_config(), make_infra())
        invoke = app.handlers["main"]

        resolved = make_resolved_config()
        events = MagicMock(spec=EventQueue)
        session_state = SessionState(resolved=resolved, events=events)

        await session_state.invocation_lock.acquire()

        app.state.app_config = make_app_config()
        app.state.infra = make_infra()
        app.state.session = session_state
        app.state.session_id = "original"

        with (
            patch(f"{_MOD_APP}.BedrockAgentCoreContext.get_session_id", return_value="different"),
            patch(f"{_MOD_APP}.resolve_session", return_value=session_state),
        ):
            results = [item async for item in invoke({"prompt": "hi"})]

        assert len(results) == 1
        assert results[0]["type"] == "error"
        assert "already running" in results[0]["data"]["message"]

        session_state.invocation_lock.release()
```

The only change: add `patch(f"{_MOD_APP}.resolve_session", return_value=session_state)`
so the test doesn't fail trying to call `load_session` on mock objects.

All other invoke tests (`TestInvokeConcurrencyGuard`,
`TestInvokeHappyPath`, `TestInvokePromptValidation`) are unaffected
because they operate on matching session IDs (session resolution is
skipped).

---

## Issue 6 — No invocation timeout

### Problem

`stream_invocation()` in `src/strands_compose_agentcore/session.py` calls
`await resolved.entry.invoke_async(prompt)` with no timeout.
An agent that hangs forever holds the `invocation_lock` forever.
The concurrency guard then rejects all subsequent requests permanently.

### Solution

Add a configurable `invocation_timeout` parameter to `stream_invocation()`.
Default to `None` (no timeout — preserving current behavior for users who
don't need it).  When set, wrap the agent invocation with
`asyncio.wait_for()`.  On timeout, emit an error event through the queue.

#### File: `src/strands_compose_agentcore/session.py`

Update `stream_invocation` signature and the `_run` inner function:

```python
async def stream_invocation(
    resolved: ResolvedConfig,
    events: EventQueue,
    prompt: str,
    *,
    invocation_timeout: float | None = None,
) -> AsyncIterator[StreamEvent]:
    """Flush stale events, invoke the entry agent, and yield events.

    Args:
        resolved: Fully resolved config with agents and entry point.
        events: The wired EventQueue shared across invocations.
        prompt: User prompt to send to the entry agent.
        invocation_timeout: Maximum seconds to wait for the agent to
            finish.  ``None`` means no timeout.

    Yields:
        StreamEvent objects as the agent runs.
    """
    events.flush()

    async def _run() -> None:
        try:
            if resolved.entry is None:
                raise RuntimeError("entry point not set in resolved config")
            coro = resolved.entry.invoke_async(prompt)
            if invocation_timeout is not None:
                await asyncio.wait_for(coro, timeout=invocation_timeout)
            else:
                await coro
        except TimeoutError:
            logger.error(
                "prompt=<%s>, timeout=<%s> | agent invocation timed out",
                prompt[:80],
                invocation_timeout,
            )
            events.put_event(
                StreamEvent(
                    type="error",
                    agent_name="",
                    timestamp=datetime.now(tz=timezone.utc),
                    data={"message": "agent invocation timed out after %s seconds" % invocation_timeout},
                )
            )
        except Exception:
            logger.exception("prompt=<%s> | agent invocation failed", prompt[:80])
            events.put_event(
                StreamEvent(
                    type="error",
                    agent_name="",
                    timestamp=datetime.now(tz=timezone.utc),
                    data={"message": "internal error during agent invocation"},
                )
            )
        finally:
            await events.close()

    task = asyncio.create_task(_run())
    while (event := await events.get()) is not None:
        yield event
    await task
```

#### File: `src/strands_compose_agentcore/app.py`

Add `invocation_timeout` parameter to `create_app()`:

```python
def create_app(
    config: str | Path | list[str | Path] | AppConfig,
    infra: ResolvedInfra | None = None,
    *,
    cors_origins: list[str] | None = None,
    suppress_runtime_logging: bool = False,
    invocation_timeout: float | None = None,
) -> BedrockAgentCoreApp:
```

Add to the docstring's Args section:

```
        invocation_timeout: Maximum seconds to wait for the agent to
            finish a single invocation.  ``None`` (the default) means
            no timeout — the agent runs until completion or failure.
```

Store it so the invoke closure can reference it:

```python
    _invocation_timeout = invocation_timeout  # capture for closure
```

Pass it through in the invoke closure:

```python
        async with session.invocation_lock:
            async for event in stream_invocation(
                session.resolved, session.events, prompt,
                invocation_timeout=_invocation_timeout,
            ):
                yield event.asdict()
```

#### Tests: `tests/test_app.py`

Add to `TestStreamInvocation`:

```python
    @pytest.mark.asyncio
    async def test_emits_timeout_event(self) -> None:
        queue: asyncio.Queue = asyncio.Queue()
        resolved = MagicMock()

        async def _slow_invoke(p):
            await asyncio.sleep(100)  # will be cancelled by timeout

        resolved.entry.invoke_async = _slow_invoke
        events = EventQueue(queue)

        results = [
            item
            async for item in stream_invocation(
                resolved, events, "hi", invocation_timeout=0.01
            )
        ]
        assert len(results) == 1
        assert results[0].type == "error"
        assert "timed out" in results[0].data["message"]

    @pytest.mark.asyncio
    async def test_no_timeout_when_none(self) -> None:
        queue: asyncio.Queue = asyncio.Queue()
        resolved = MagicMock()
        resolved.entry.invoke_async = AsyncMock(return_value=None)
        events = EventQueue(queue)

        results = [
            item
            async for item in stream_invocation(
                resolved, events, "hi", invocation_timeout=None
            )
        ]
        assert results == []
```

---

## Issue 7 — No built-in retry/backoff in AgentCoreClient

### Problem

`ThrottledError` is raised by `AgentCoreClient.invoke()` but the user has
to implement their own retry loop.  For a production client, even basic
retry with exponential backoff and jitter is table stakes.

### Solution

Add a `RetryConfig` dataclass and a retry wrapper to
`src/strands_compose_agentcore/client/utils.py`, and wire it into
`AgentCoreClient.__init__` and `invoke`.

#### File: `src/strands_compose_agentcore/client/utils.py`

Add after the exception classes, before `_ERROR_MAP`:

```python
@dataclass
class RetryConfig:
    """Configuration for exponential backoff retry on throttled requests.

    Args:
        max_retries: Maximum number of retry attempts.  0 means no retries.
        base_delay: Initial delay in seconds before the first retry.
        max_delay: Maximum delay in seconds between retries.
        jitter: Whether to add random jitter (0 to base_delay) to each delay.
    """

    max_retries: int = 3
    base_delay: float = 1.0
    max_delay: float = 30.0
    jitter: bool = True
```

Add `RetryConfig` to `__all__`.

Add `dataclass` to imports (`from dataclasses import dataclass`).

#### File: `src/strands_compose_agentcore/client/agentcore.py`

1. Import `RetryConfig` from `.utils`:

```python
from .utils import (
    AgentCoreClientError,
    RetryConfig,
    _translate_error,
    parse_sse_line,
)
```

2. Add `retry` parameter to `__init__`:

```python
    def __init__(
        self,
        agent_runtime_arn: str,
        *,
        region: str | None = None,
        session: boto3.Session | None = None,
        timeout: float | None = None,
        max_concurrent_streams: int = 64,
        retry: RetryConfig | None = None,
    ) -> None:
```

Store it: `self._retry = retry or RetryConfig(max_retries=0)`

Add to docstring Args:

```
            retry: Retry configuration for throttled requests.
                ``None`` disables retry (default).  Pass
                ``RetryConfig()`` for sensible defaults (3 retries,
                exponential backoff with jitter).
```

3. Wrap the `run_in_executor` call in `invoke()` with retry logic:

```python
        import random

        last_exc: AgentCoreClientError | None = None
        for attempt in range(1 + self._retry.max_retries):
            try:
                response = await loop.run_in_executor(
                    self._executor, self._invoke_sync, session_id, prompt, payload_extras
                )
                break
            except ThrottledError as exc:
                last_exc = exc
                if attempt >= self._retry.max_retries:
                    raise
                delay = min(
                    self._retry.base_delay * (2 ** attempt),
                    self._retry.max_delay,
                )
                if self._retry.jitter:
                    delay += random.uniform(0, self._retry.base_delay)  # noqa: S311
                logger.info(
                    "attempt=<%d>, delay=<%0.2f> | throttled, retrying",
                    attempt + 1,
                    delay,
                )
                await asyncio.sleep(delay)
            except AgentCoreClientError:
                raise
            except Exception as exc:
                raise AgentCoreClientError(str(exc)) from exc
        else:
            raise last_exc  # type: ignore[misc]  # all retries exhausted
```

4. Also re-export `RetryConfig` from `src/strands_compose_agentcore/client/__init__.py`
and `src/strands_compose_agentcore/__init__.py`, and add it to both `__all__` lists.

#### Tests: `tests/test_client_agentcore.py`

Add a new test class `TestInvokeRetry`:

```python
class TestInvokeRetry:
    @pytest.mark.asyncio
    async def test_retries_on_throttling(self, mock_boto3_session: MagicMock) -> None:
        from strands_compose_agentcore.client.utils import RetryConfig

        client = AgentCoreClient(
            _TEST_ARN,
            session=mock_boto3_session,
            retry=RetryConfig(max_retries=2, base_delay=0.01, jitter=False),
        )
        body = _make_streaming_body([_make_sse_line("complete", "a")])

        # Fail twice, succeed on third attempt.
        client._client.invoke_agent_runtime.side_effect = [
            _make_client_error("ThrottlingException"),
            _make_client_error("ThrottlingException"),
            {"response": body},
        ]
        events = [e async for e in client.invoke(session_id=_VALID_SESSION_ID, prompt="Hi")]
        assert len(events) == 1
        assert client._client.invoke_agent_runtime.call_count == 3

    @pytest.mark.asyncio
    async def test_raises_after_max_retries(self, mock_boto3_session: MagicMock) -> None:
        from strands_compose_agentcore.client.utils import RetryConfig

        client = AgentCoreClient(
            _TEST_ARN,
            session=mock_boto3_session,
            retry=RetryConfig(max_retries=1, base_delay=0.01, jitter=False),
        )
        client._client.invoke_agent_runtime.side_effect = _make_client_error("ThrottlingException")
        with pytest.raises(ThrottledError):
            async for _ in client.invoke(session_id=_VALID_SESSION_ID, prompt="Hi"):
                pass

    @pytest.mark.asyncio
    async def test_no_retry_on_access_denied(self, mock_boto3_session: MagicMock) -> None:
        from strands_compose_agentcore.client.utils import RetryConfig

        client = AgentCoreClient(
            _TEST_ARN,
            session=mock_boto3_session,
            retry=RetryConfig(max_retries=3, base_delay=0.01),
        )
        client._client.invoke_agent_runtime.side_effect = _make_client_error("AccessDeniedException")
        with pytest.raises(AccessDeniedError):
            async for _ in client.invoke(session_id=_VALID_SESSION_ID, prompt="Hi"):
                pass
        assert client._client.invoke_agent_runtime.call_count == 1

    @pytest.mark.asyncio
    async def test_no_retry_by_default(self, mock_boto3_session: MagicMock) -> None:
        client = AgentCoreClient(_TEST_ARN, session=mock_boto3_session)
        client._client.invoke_agent_runtime.side_effect = _make_client_error("ThrottlingException")
        with pytest.raises(ThrottledError):
            async for _ in client.invoke(session_id=_VALID_SESSION_ID, prompt="Hi"):
                pass
        assert client._client.invoke_agent_runtime.call_count == 1
```

---

## Issue 8 — Private `_translate_error` imported across modules

### Problem

`src/strands_compose_agentcore/client/agentcore.py` imports
`_translate_error` from `src/strands_compose_agentcore/client/utils.py`.
The underscore prefix signals "private, don't import this."  But the
function is used across module boundaries in production code — it is
effectively a public utility.

### Solution

Rename `_translate_error` → `translate_error` everywhere.  Add it to
`__all__` in `utils.py`.  Do **not** re-export it from `client/__init__.py`
or the top-level `__init__.py` — it is a subpackage-internal utility, not
part of the user-facing API.

#### File: `src/strands_compose_agentcore/client/utils.py`

1. Rename the function: `def _translate_error(` → `def translate_error(`
2. Rename the internal reference from `_ERROR_MAP` — no change needed, it
   is only used inside `translate_error`.
3. Add `"translate_error"` to `__all__`.

#### File: `src/strands_compose_agentcore/client/agentcore.py`

1. Update the import: `_translate_error` → `translate_error`.
2. Update the usage on line 303: `raise _translate_error(exc)` →
   `raise translate_error(exc)`.

#### File: `tests/test_client_agentcore.py`

1. Update the import on line 21: `_translate_error` → `translate_error`.
2. Update all five usages in `TestTranslateError`:
   `_translate_error(err)` → `translate_error(err)`.

Run `grep -rn '_translate_error' src/ tests/` to verify no stale
references remain.

---

## Issue 9 — Weak CORS middleware test

### Problem

In `tests/test_app.py`, `test_cors_middleware_added_when_origins_provided`
asserts:

```python
assert (
    any("CORS" in t or "cors" in t.lower() for t in middleware_types)
    or len(app.user_middleware) > 0
)
```

The `or len(app.user_middleware) > 0` branch makes the test pass if
**any** middleware is present, regardless of whether it is CORS.
This is vacuously true whenever any middleware exists.

### Solution

Replace the assertion with a precise check for `CORSMiddleware`:

```python
    def test_cors_middleware_added_when_origins_provided(self) -> None:
        from starlette.middleware.cors import CORSMiddleware

        app = create_app(
            make_app_config(),
            make_infra(),
            cors_origins=["http://localhost:3000"],
        )
        middleware_classes = [m.cls for m in app.user_middleware]
        assert CORSMiddleware in middleware_classes
```

This imports the actual class and checks for identity, not string matching.
No fallback `or` clause.

---

## Issue 10 — Coverage threshold too low (70%)

### Problem

The coverage threshold is 70% in 12 locations across the repo.
For a ~400 LOC library with an extensive test suite, 70% is trivially
achievable and signals low aspiration.

### Solution

Raise the threshold to 90% in every location.
First, run `uv run just test` to verify current coverage is already ≥ 90%.
If it is not, add tests to reach 90% before changing the threshold.

#### Files to update (literal string replacements):

| File | Old | New |
|------|-----|-----|
| `tasks/test.just` | `cov_fail_under="70"` | `cov_fail_under="90"` |
| `AGENTS.md` | `pytest with coverage (≥70%)` | `pytest with coverage (≥90%)` |
| `CONTRIBUTING.md` | `pytest with coverage (≥70%)` | `pytest with coverage (≥90%)` |
| `.github/copilot-instructions.md` | `pytest with coverage (≥70%)` | `pytest with coverage (≥90%)` |
| `.github/agents/developer.agent.md` (line 22) | `pytest with coverage (≥70%)` | `pytest with coverage (≥90%)` |
| `.github/agents/developer.agent.md` (line 35) | `coverage must remain ≥ 70%` | `coverage must remain ≥ 90%` |
| `.github/agents/reviewer.agent.md` (line 20) | `pytest with coverage (≥70%)` | `pytest with coverage (≥90%)` |
| `.github/agents/tester.agent.md` (line 16) | `pytest with coverage (≥70%)` | `pytest with coverage (≥90%)` |
| `.github/agents/tester.agent.md` (line 27) | `coverage must remain ≥ 70%` | `coverage must remain ≥ 90%` |
| `.github/PULL_REQUEST_TEMPLATE.md` (line 29) | `coverage ≥ 70%` | `coverage ≥ 90%` |
| `.github/instructions/tests.instructions.md` (line 19) | `Coverage must remain ≥ 70%` | `Coverage must remain ≥ 90%` |
| `.github/skills/check-and-test/SKILL.md` (line 40) | `**≥ 70%**` | `**≥ 90%**` |

**NOTE:** If Issue 4 (Copilot instruction drift) is implemented first and
the copilot-instructions.md no longer contains the coverage line, skip
that file.

Run `uv run just test` after all changes to verify the new threshold passes.

---

## Issue 11 — AGENTS.md directory listing is stale

### Problem

The directory structure in `AGENTS.md` (lines ~85–130) lists docs ending
at `Chapter_08.md` and `Quick_Recipes.md`.  `Chapter_09.md` exists in the
repo and is referenced from `README.md`, `docs/README.md`, and
`docs/Chapter_08.md`, but is missing from the AGENTS.md listing.

It also does not list `_utils.py` in the source tree, and the `tests/`
listing doesn't match actual test files.

### Solution

Replace the entire directory structure block in `AGENTS.md` with the
current accurate tree:

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

Find the old tree block (starts with ` ```  ` after `## Directory Structure`)
and replace it entirely with the block above.

---

## Execution Order Recommendation

Issues are independent, but for minimal merge conflicts:

1. **Issue 2** (dead fixtures) — zero risk, pure deletion
2. **Issue 8** (`_translate_error` rename) — mechanical rename
3. **Issue 9** (CORS test) — one assertion change
4. **Issue 11** (AGENTS.md tree) — docs only
5. **Issue 4** (Copilot instructions) — docs only
6. **Issue 10** (coverage threshold) — config only, run tests first
7. **Issue 1** (session ID server validation) — adds code + tests
8. **Issue 5** (concurrency guard) — restructures app.py invoke flow
9. **Issue 6** (invocation timeout) — adds parameter to session.py + app.py
10. **Issue 7** (retry/backoff) — new feature in client
11. **Issue 3** (REPL event loop) — rework of repl() internals

Issues 1, 5, 6 all touch `app.py` — implement them in that order to avoid
conflicts.  Issues 7 and 8 both touch `client/agentcore.py` and
`client/utils.py` — implement 8 before 7.
