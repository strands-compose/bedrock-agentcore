# Test Patterns — the toolbox

Concrete, copy-paste templates for the doctrine in `SKILL.md`. Load this only
when actually writing a test. Exact names drift — trust the **shapes** and adapt
to the current public API (`strands_compose_agentcore/__init__.py`) and module
structure.

Everything here obeys the doctrine: **fake strands-compose at our own
resolution/invocation seam** (or use a real object), **fake transports at the
vendor's test seam** (`botocore.Stubber`, `httpx.MockTransport`), **control
timing with gates, never sleeps**, and **assert on shape / type / yielded-event
order — never on private members, mock calls, or message prose.**

---

## 1. Owned fakes — `tests/fakes/compose.py`

One authoritative fake per external seam. `FakeEntry` covers every entry-agent
outcome the doctrine cares about — success, raise, timeout/never-complete, and a
gated run for deterministic concurrency tests. `EventQueue` and `SessionManifest`
are **real** (owned by strands-compose, cheap, deterministic).

```python
from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any

from strands_compose import EventQueue
from strands_compose.types import SessionManifest

from tests.factories import minimal_manifest


class FakeEntry:
    """Stands in for a resolved entry agent / orchestration.

    ``invoke_async`` returns a canned result, raises a configured error, or —
    when ``gate`` is set — waits on that event so a test can control *when* the
    run completes (timeout, cancellation, "still running" / busy).
    """

    def __init__(
        self,
        *,
        result: Any = None,
        error: Exception | None = None,
        gate: asyncio.Event | None = None,
    ) -> None:
        self.result = result
        self.error = error
        self.gate = gate
        self.calls: list[Any] = []

    async def invoke_async(self, agent_input: Any) -> Any:
        self.calls.append(agent_input)
        if self.gate is not None:
            await self.gate.wait()      # never returns until the test sets it
        if self.error is not None:
            raise self.error
        return self.result


@dataclass
class FakeResolvedConfig:
    """Minimal stand-in for strands_compose.ResolvedConfig.

    Only the fields our adapter reads are present.
    """

    entry: FakeEntry = field(default_factory=FakeEntry)
    agents: dict = field(default_factory=dict)
    orchestrators: dict = field(default_factory=dict)


@dataclass
class FakeSessionState:
    """Pre-built SessionState for app entrypoint tests.

    Mirrors the real ``SessionState``: a resolved config, a real EventQueue, a
    real manifest, a session id, and a real asyncio.Lock (so locking tests use
    the real primitive).
    """

    resolved: FakeResolvedConfig = field(default_factory=FakeResolvedConfig)
    events: EventQueue = field(default_factory=lambda: EventQueue(asyncio.Queue()))
    manifest: SessionManifest = field(default_factory=minimal_manifest)
    session_id: str | None = "a-session-id-long-enough-to-pass-validation-0001"
    invocation_lock: asyncio.Lock = field(default_factory=asyncio.Lock)
```

A resolved agent is **not** hand-faked: `close_session` narrows with
`isinstance(node, Agent)`, so a double must carry the spec.

```python
from unittest.mock import Mock

from strands import Agent

agent = Mock(spec=Agent)                       # passes isinstance, records cleanup()
failing = Mock(spec=Agent)
failing.cleanup.side_effect = RuntimeError("boom")
```

---

## 2. Transport fakes — `tests/fakes/transport.py`

Fake at the vendor test seam so request shapes stay validated.

```python
from __future__ import annotations

from contextlib import contextmanager

import httpx


class FakeUrlopenResponse:
    """Stands in for the urllib response context manager used by LocalClient.

    Iterating yields raw SSE ``bytes`` lines, matching ``for raw_line in resp``.
    """

    def __init__(self, lines: list[bytes]) -> None:
        self._lines = lines

    def __enter__(self) -> "FakeUrlopenResponse":
        return self

    def __exit__(self, *exc: object) -> None:
        return None

    def __iter__(self):
        return iter(self._lines)


def sse_transport(lines: list[str]) -> httpx.MockTransport:
    """An httpx.MockTransport that streams the given SSE lines for AsyncLocalClient."""
    body = "".join(f"{line}\n" for line in lines).encode()

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=body, headers={"content-type": "text/event-stream"})

    return httpx.MockTransport(handler)


@contextmanager
def stubbed_agentcore(client, response: dict | None = None, error=None):
    """Yield a botocore Stubber primed on the AgentCoreClient's boto3 client.

    Use ``add_response`` (validates the request shape against the real API) or
    ``add_client_error`` to force a ClientError. See tests/client/test_agentcore.py.
    """
    from botocore.stub import Stubber

    stubber = Stubber(client._client)
    with stubber:
        yield stubber
```

---

## 3. Payload / body builders — `tests/factories.py`

```python
from __future__ import annotations

import base64
from typing import Any

from strands_compose import AppConfig, load_config
from strands_compose.types import EntryDescriptor, SessionManifest


def payload(prompt: Any = "Hello") -> dict[str, Any]:
    """A minimal valid invocation payload. Override prompt to test variants."""
    return {"prompt": prompt}


def image_payload(*, format: str = "png", data: bytes = b"\x89PNG\r\n\x1a\n") -> dict[str, Any]:
    return {"prompt": [{"image": {"format": format, "source": {"base64": _b64(data)}}}]}


def document_payload(
    *, format: str = "pdf", name: str = "report.pdf", data: bytes = b"%PDF-1.4"
) -> dict[str, Any]:
    return {
        "prompt": [
            {"document": {"format": format, "name": name, "source": {"base64": _b64(data)}}}
        ]
    }


def reply_payload(interrupt_id: str = "int-001", response: Any = "yes") -> dict[str, Any]:
    return {"prompt": [{"reply": {"interrupt_id": interrupt_id, "response": response}}]}


def _b64(data: bytes) -> str:
    return base64.b64encode(data).decode("ascii")


# Standard limit kwargs for parse_payload; override only what a test cares about.
LIMITS: dict[str, Any] = {
    "max_payload_bytes": 1024 * 1024,
    "max_media_bytes": 1024 * 1024,
    "max_media_blocks": 5,
}


def minimal_app_config() -> AppConfig:
    """The smallest config that validates -- one agent, no model, no MCP."""
    return load_config("agents:\n  helper:\n    system_prompt: hi\nentry: helper\n")


def minimal_manifest() -> SessionManifest:
    """A real, empty SessionManifest -- enough for emit_session_start."""
    return SessionManifest(
        agents=[], orchestrations=[], entry=EntryDescriptor(name="entry", kind="agent")
    )
```

`minimal_app_config()` lets `create_app` run its real `load_config` path without
touching the filesystem, so no factory-level patching is needed.

---

## 4. The wire round-trip — `tests/contract/test_roundtrip.py`

The single most valuable test: a block built on the client survives assembly and
parses to the expected Strands shape on the server. Catches client/server drift.

```python
from __future__ import annotations

from strands_compose_agentcore import document, image, reply, text
from strands_compose_agentcore.client.utils import build_invocation_body
from strands_compose_agentcore.payload import parse_payload
from tests.factories import LIMITS


def test_text_block_round_trips_to_strands_shape():
    body = build_invocation_body([text("hello")])
    result = parse_payload(body, **LIMITS)
    assert result == [{"text": "hello"}]


def test_image_block_round_trips_bytes():
    body = build_invocation_body([image(b"\x89PNG\r\n\x1a\n", format="png")])
    result = parse_payload(body, **LIMITS)
    assert result[0]["image"]["format"] == "png"
    assert isinstance(result[0]["image"]["source"]["bytes"], bytes)


def test_reply_block_round_trips_to_interrupt_response():
    body = build_invocation_body([reply("int-1", "yes")])
    result = parse_payload(body, **LIMITS)
    assert result == [{"interruptId": "int-1", "response": "yes"}]
```

---

## 5. Payload parsing — `tests/server/test_payload.py`

Assert the decoded value's type/structure, or the exception *type*. `match=`
targets a stable field/limit token only.

```python
from __future__ import annotations

import pytest

from strands_compose_agentcore.payload import MultimodalPayloadError, parse_payload
from tests.factories import LIMITS, image_payload, payload


def test_string_prompt_returns_str():
    assert parse_payload(payload("Hi"), **LIMITS) == "Hi"


def test_image_block_decodes_base64_to_bytes():
    result = parse_payload(image_payload(), **LIMITS)
    assert isinstance(result[0]["image"]["source"]["bytes"], bytes)


def test_missing_prompt_raises_payload_error():
    # type is contract; 'prompt' is a stable wire-field token, not prose.
    with pytest.raises(MultimodalPayloadError, match="prompt"):
        parse_payload({}, **LIMITS)


def test_oversized_payload_rejected():
    with pytest.raises(MultimodalPayloadError, match="max_payload_bytes"):
        parse_payload(payload("x" * 1000), **{**LIMITS, "max_payload_bytes": 10})


@pytest.mark.parametrize("bad_format", ["bmp", "tiff", "mp4"])
def test_unsupported_image_format_rejected(bad_format):
    with pytest.raises(MultimodalPayloadError):
        parse_payload(image_payload(format=bad_format), **LIMITS)
```

---

## 6. Session resolution, teardown, entry-agent run — `tests/server/test_session.py`

Real `EventQueue`; `FakeEntry` controls the outcome. Assert events-on-queue and
that the queue closes (drain to `None`). Gates, not sleeps.

```python
from __future__ import annotations

import asyncio
from unittest.mock import Mock, patch

import pytest
from strands import Agent
from strands_compose import EventQueue

from strands_compose_agentcore.session import close_session, resolve_session, run_entry_agent
from tests.factories import minimal_manifest
from tests.fakes.compose import FakeEntry, FakeResolvedConfig, FakeSessionState


async def _drain(events) -> list:
    collected = []
    while (ev := await events.get()) is not None:
        collected.append(ev)
    return collected


def test_resolve_session_threads_session_id():
    # build_manifest needs real resolved agents, so it is patched at our seam.
    with (
        patch("strands_compose_agentcore.session.load", return_value=FakeResolvedConfig()),
        patch("strands_compose_agentcore.session.build_manifest", return_value=minimal_manifest()),
    ):
        state = resolve_session(object(), "a-session-id-long-enough-to-pass-0001")

    assert state.session_id == "a-session-id-long-enough-to-pass-0001"


def test_close_session_continues_after_a_failing_agent():
    failing, healthy = Mock(spec=Agent), Mock(spec=Agent)
    failing.cleanup.side_effect = RuntimeError("boom")
    state = FakeSessionState(
        resolved=FakeResolvedConfig(agents={"bad": failing, "good": healthy}),
    )

    close_session(state)

    healthy.cleanup.assert_called_once()


async def test_run_closes_queue_on_success():
    resolved = FakeResolvedConfig(entry=FakeEntry(result="done"))
    events = EventQueue(asyncio.Queue(), session_id="s")

    await run_entry_agent(resolved, events, "Hello")

    collected = await _drain(events)
    assert any(e.type == "session_end" for e in collected)


async def test_run_times_out_via_gate_not_clock():
    gate = asyncio.Event()  # never set -> entry never completes on its own
    resolved = FakeResolvedConfig(entry=FakeEntry(gate=gate))
    events = EventQueue(asyncio.Queue(), session_id="s")

    await run_entry_agent(resolved, events, "Hello", invocation_timeout=0.01)

    collected = await _drain(events)
    assert any(e.type == "error" for e in collected)


@pytest.mark.parametrize("bad", [0, -1, float("nan")])
async def test_non_positive_timeout_raises(bad):
    resolved = FakeResolvedConfig()
    events = EventQueue(asyncio.Queue())
    with pytest.raises(ValueError, match="invocation_timeout"):
        await run_entry_agent(resolved, events, "Hi", invocation_timeout=bad)
```

---

## 7. App streaming, faults, locking — `tests/server/test_app.py`

Drive the ASGI app; fake `resolve_session`. Assert lifecycle *order* and that
failures degrade to an error event. Mark `integration`.

```python
from __future__ import annotations

from unittest.mock import patch

import pytest
from starlette.testclient import TestClient

from strands_compose_agentcore.app import create_app
from tests.fakes.compose import FakeSessionState

_SID = {"X-Amzn-Bedrock-AgentCore-Runtime-Session-Id": "a-session-id-long-enough-to-pass-0001"}
pytestmark = pytest.mark.integration


def test_invalid_payload_yields_error_event(app):
    client = TestClient(app, raise_server_exceptions=False)
    resp = client.post("/invocations", json={}, headers=_SID)
    assert resp.status_code == 200          # SSE always 200
    assert "error" in resp.text             # degraded, did not crash


def test_busy_session_is_rejected(app):
    session = FakeSessionState()

    async def _hold():
        await session.invocation_lock.acquire()

    with patch("strands_compose_agentcore.app.resolve_session", return_value=session):
        client = TestClient(app, raise_server_exceptions=False)
        # Prime the cache and hold the lock so the next request sees "busy".
        client.portal.call(_hold)          # acquire the real lock off-loop
        app.state.session = session
        resp = client.post("/invocations", json={"prompt": "Hi"}, headers=_SID)
        assert "error" in resp.text
```

> The entrypoint reads `session.manifest`, so faking `resolve_session` is enough —
> nothing else needs patching. For full-fidelity end-to-end tests, build the app
> from a tiny real YAML with the model provider faked at strands-compose's
> `resolve_model` seam (see the `library-development` skill); that runs real
> `load` + `build_manifest`.

---

## 8. Client transport — `tests/client/`

### Local (urllib) — fake the response

```python
from __future__ import annotations

from unittest.mock import patch

from strands_compose_agentcore import LocalClient
from tests.fakes.transport import FakeUrlopenResponse

_EVENT = b'data: {"type": "token", "agent_name": "a", "data": {"text": "hi"}}'


def test_local_client_yields_stream_events():
    with patch("strands_compose_agentcore.client.local.urlopen",
               return_value=FakeUrlopenResponse([_EVENT, b"", b": keepalive"])):
        events = list(LocalClient().invoke("Hello"))
    assert [e.type for e in events] == ["token"]   # noise filtered
```

### Async (httpx) — MockTransport

```python
from __future__ import annotations

import httpx
import pytest

from strands_compose_agentcore import AsyncLocalClient
from strands_compose_agentcore.types import ClientConnectionError
from tests.fakes.transport import sse_transport

_LINE = 'data: {"type": "token", "agent_name": "a", "data": {"text": "hi"}}'


async def test_async_local_client_yields_events():
    client = AsyncLocalClient()
    client._http = httpx.AsyncClient(transport=sse_transport([_LINE]))
    events = [e async for e in client.invoke("Hello")]
    assert [e.type for e in events] == ["token"]


async def test_async_local_client_connect_error_is_translated():
    def boom(request):
        raise httpx.ConnectError("refused")

    client = AsyncLocalClient()
    client._http = httpx.AsyncClient(transport=httpx.MockTransport(boom))
    with pytest.raises(ClientConnectionError):
        [e async for e in client.invoke("Hello")]
```

### AgentCore (boto3) — botocore Stubber

```python
from __future__ import annotations

import io

from strands_compose_agentcore import AgentCoreClient

_ARN = "arn:aws:bedrock-agentcore:us-east-1:0:runtime/x"
_SID = "a-session-id-long-enough-to-pass-validation-0001"


async def test_agentcore_client_streams_events():
    client = AgentCoreClient(_ARN, region="us-east-1")
    body = b'data: {"type": "token", "agent_name": "a", "data": {"text": "hi"}}\n'
    from botocore.stub import Stubber

    with Stubber(client._client) as stub:
        stub.add_response(
            "invoke_agent_runtime",
            {"response": io.BytesIO(body)},
            # expected params are validated -> a wrong key would fail loudly
            expected_params={
                "agentRuntimeArn": _ARN,
                "payload": b'{"prompt": "Hi"}',
                "contentType": "application/json",
                "accept": "text/event-stream",
                "runtimeSessionId": _SID,
            },
        )
        events = [e async for e in client.invoke("Hi", session_id=_SID)]
    assert [e.type for e in events] == ["token"]
    client.close()
```

---

## 9. Error translation — `tests/client/test_errors.py`

```python
from __future__ import annotations

import pytest

from strands_compose_agentcore.client.utils import translate_error
from strands_compose_agentcore.types import (
    AccessDeniedError,
    AgentCoreClientError,
    ConflictError,
    InvalidRequestError,
    SessionNotFoundError,
    ThrottledError,
)


class _FakeClientError(Exception):
    def __init__(self, code: str) -> None:
        self.response = {"Error": {"Code": code, "Message": "msg"}}


@pytest.mark.parametrize(
    "code,expected",
    [
        ("AccessDeniedException", AccessDeniedError),
        ("ThrottlingException", ThrottledError),
        ("ResourceNotFoundException", SessionNotFoundError),
        ("ValidationException", InvalidRequestError),
        ("ConflictException", ConflictError),
        ("SomethingElse", AgentCoreClientError),
    ],
)
def test_error_code_maps_to_typed_exception(code, expected):
    assert isinstance(translate_error(_FakeClientError(code)), expected)
```

---

## 10. SSE parsing — `tests/client/test_sse.py`

```python
from __future__ import annotations

import pytest

from strands_compose_agentcore.client.utils import parse_sse_line

_VALID = 'data: {"type": "token", "agent_name": "a", "data": {"text": "hi"}}'


def test_valid_data_line_parses_to_event():
    assert parse_sse_line(_VALID).type == "token"


@pytest.mark.parametrize("noise", ["", ": comment", "keepalive", "data: not-json"])
def test_noise_lines_return_none(noise):
    assert parse_sse_line(noise) is None
```

---

## 11. Media builders — `tests/media/test_builders.py`

```python
from __future__ import annotations

import base64
from pathlib import Path

import pytest

from strands_compose_agentcore import document, image, reply, text


def test_text_block_shape():
    assert text("hi") == {"text": "hi"}


def test_image_from_bytes_requires_format():
    with pytest.raises(ValueError, match="format"):
        image(b"\x89PNG", format=None)


def test_image_from_path_infers_format(tmp_path: Path):
    f = tmp_path / "photo.jpeg"
    f.write_bytes(b"\xff\xd8\xff\xe0")
    assert image(f)["image"]["format"] == "jpeg"


def test_missing_path_raises_file_not_found(tmp_path: Path):
    with pytest.raises(FileNotFoundError):
        image(tmp_path / "nope.png")


def test_document_defaults_name_with_suffix(tmp_path: Path):
    f = tmp_path / "report.pdf"
    f.write_bytes(b"%PDF-1.4")
    assert document(f)["document"]["name"].startswith("report-")


def test_reply_block_shape():
    assert reply("int-1", "yes") == {"reply": {"interrupt_id": "int-1", "response": "yes"}}
```

---

## 12. Format registry (example-based, not property) — `tests/media/test_formats.py`

```python
from __future__ import annotations

from strands_compose_agentcore.media_formats import MEDIA_FORMATS
from strands_compose_agentcore.types import DOCUMENT_FORMATS, IMAGE_FORMATS


def test_image_and_document_sets_are_disjoint():
    assert IMAGE_FORMATS & DOCUMENT_FORMATS == frozenset()


def test_sets_cover_every_registered_format():
    assert IMAGE_FORMATS | DOCUMENT_FORMATS == {s.format for s in MEDIA_FORMATS}
```

---

## 13. Property tests (optional; needs `hypothesis` in dev deps) — `tests/property/`

Only genuine runtime invariants. Not the format table, not base64.

```python
from __future__ import annotations

import pytest

pytest.importorskip("hypothesis")
from hypothesis import given, strategies as st  # noqa: E402

from strands_compose_agentcore._utils import validate_session_id  # noqa: E402


@given(st.text(min_size=33, max_size=256))
def test_in_range_session_ids_accepted(sid):
    validate_session_id(sid)  # must not raise


@given(st.text(max_size=32))
def test_short_session_ids_rejected(sid):
    with pytest.raises(ValueError):
        validate_session_id(sid)
```

---

## Quick decision guide

| I'm testing... | Folder | Fake at? | Assert on |
|---|---|---|---|
| payload shape / rejection | `server/` | nothing | decoded value type+structure, or exception type |
| client↔server drift | `contract/` | nothing | round-trip parsed shape |
| body assembly | `client/` | nothing | `{"prompt": ...}` shape / `ValueError` |
| SSE line parsing | `client/` | nothing | `StreamEvent` or `None` |
| error code translation | `client/` | nothing | exception type |
| entry-agent run + faults | `server/` | `FakeEntry` (gate/raise) | error event present, queue closed |
| session teardown | `server/` | `Mock(spec=Agent)` | `cleanup()` called per agent, failures survived |
| app streaming / caching / locking | `server/` (integration) | `resolve_session` | lifecycle order, error-event on failure |
| LocalClient invoke | `client/` | fake `urlopen` response | yielded events, noise filtered |
| AsyncLocalClient invoke / connect error | `client/` | `httpx.MockTransport` | yielded events / `ClientConnectionError` |
| AgentCoreClient invoke / stop / throttle | `client/` | `botocore.Stubber` | yielded events, typed error, validated request |
| media builders | `media/` | nothing (`tmp_path`) | dict shape, format, decoded bytes |
| format registry | `media/` | nothing | disjoint + covers table |
| session id validation | `property/` or util | nothing | accepted / `ValueError` |
| CLI dispatch | `cli/` | command internals | `CLIError` / correct dispatch |
| wire shape guard | `contract/` | nothing | body keys + error-event shape (one snapshot) |
