# Test Patterns -- the toolbox

Concrete, copy-paste templates for the doctrine in `SKILL.md`. Load this only
when actually writing a test. Exact names drift -- trust the **shapes** and
adapt to the current public API (`strands_compose_agentcore/__init__.py`) and
the module structure.

Everything here obeys two rules from the doctrine: **fake strands-compose at our
own resolution/invocation seam**, and **assert on shape / type / yielded event /
raised exception -- never on private members, mock calls, or message text.**

---

## 1. Owned fakes -- `tests/fakes/compose.py`

One authoritative fake per external seam. These stand in for strands-compose
resolution and agent execution so tests never hit a real model, MCP server, or
network.

```python
from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any

from strands_compose import EventQueue, StreamEvent


class FakeEntry:
    """Stands in for a resolved entry agent/orchestration.

    ``invoke_async`` returns immediately with a canned result, or raises
    a configured exception.  No real model call, no real strands Agent.
    """

    def __init__(
        self,
        *,
        result: Any = None,
        error: Exception | None = None,
        delay: float = 0,
    ) -> None:
        self.result = result
        self.error = error
        self.delay = delay
        self.calls: list[Any] = []

    async def invoke_async(self, agent_input: Any) -> Any:
        self.calls.append(agent_input)
        if self.delay:
            await asyncio.sleep(self.delay)
        if self.error:
            raise self.error
        return self.result


@dataclass
class FakeResolvedConfig:
    """Minimal stand-in for strands_compose.ResolvedConfig.

    Only the fields our adapter actually reads are present:
    ``entry``, ``agents``, ``orchestrators``.
    """

    entry: FakeEntry = field(default_factory=FakeEntry)
    agents: dict = field(default_factory=dict)
    orchestrators: dict = field(default_factory=dict)

    def wire_event_queue(self, session_id: str | None = None) -> EventQueue:
        """Return a real EventQueue wired to nothing (no hooks to fire)."""
        from strands_compose import EventQueue

        return EventQueue(session_id=session_id)


@dataclass
class FakeSessionState:
    """Pre-built SessionState for app entrypoint tests.

    Pre-loaded with a FakeResolvedConfig and a real EventQueue so the
    entrypoint can drain events without hitting strands-compose.
    """

    resolved: FakeResolvedConfig = field(default_factory=FakeResolvedConfig)
    events: EventQueue = field(default_factory=EventQueue)
    session_id: str | None = "test-session-id-that-is-long-enough-for-validation"
    invocation_lock: asyncio.Lock = field(default_factory=asyncio.Lock)
```

---

## 2. Payload builders -- `tests/factories.py`

Builders make relevant inputs visible and hide boilerplate. Provide both raw
dict builders (for `parse_payload` tests) and content-block builders (for client
tests).

```python
from __future__ import annotations

import base64
from typing import Any


def payload(prompt: str | dict | list = "Hello") -> dict[str, Any]:
    """A minimal valid invocation payload. Override prompt to test variants."""
    return {"prompt": prompt}


def image_payload(
    *,
    format: str = "png",
    data: bytes = b"\x89PNG\r\n\x1a\n" + b"\x00" * 100,
) -> dict[str, Any]:
    """A payload containing one image block with valid base64 source."""
    return {
        "prompt": [
            {
                "image": {
                    "format": format,
                    "source": {"base64": base64.b64encode(data).decode()},
                }
            }
        ]
    }


def document_payload(
    *,
    format: str = "pdf",
    name: str = "report",
    data: bytes = b"%PDF-1.4" + b"\x00" * 100,
) -> dict[str, Any]:
    """A payload containing one document block with valid base64 source."""
    return {
        "prompt": [
            {
                "document": {
                    "format": format,
                    "name": name,
                    "source": {"base64": base64.b64encode(data).decode()},
                }
            }
        ]
    }


def reply_payload(
    interrupt_id: str = "int-001",
    response: Any = "yes",
) -> dict[str, Any]:
    """A payload containing one reply block."""
    return {
        "prompt": [{"reply": {"interrupt_id": interrupt_id, "response": response}}]
    }


def text_block_payload(text: str = "Hello world") -> dict[str, Any]:
    """A payload containing one text block."""
    return {"prompt": [{"text": text}]}
```

---

## 3. Payload parsing tests -- `tests/server/test_payload.py`

Test through the public `parse_payload` function. Assert on the decoded value's
type and structure, or the exception type.

```python
from __future__ import annotations

import pytest

from strands_compose_agentcore.payload import MultimodalPayloadError, parse_payload
from tests.factories import document_payload, image_payload, payload, reply_payload


def test_string_prompt_returns_str():
    result = parse_payload(payload("Hi"), max_payload_bytes=None, max_media_bytes=20_000_000, max_media_blocks=20)
    assert result == "Hi"


def test_image_block_decodes_base64_to_bytes():
    result = parse_payload(
        image_payload(),
        max_payload_bytes=None,
        max_media_bytes=20_000_000,
        max_media_blocks=20,
    )
    assert isinstance(result, list)
    assert "image" in result[0]
    assert isinstance(result[0]["image"]["source"]["bytes"], bytes)


def test_oversized_payload_raises_error():
    big = payload("x" * 1000)
    with pytest.raises(MultimodalPayloadError, match="max_payload_bytes"):
        parse_payload(big, max_payload_bytes=10, max_media_bytes=20_000_000, max_media_blocks=20)


def test_missing_prompt_raises_error():
    with pytest.raises(MultimodalPayloadError, match="prompt"):
        parse_payload({}, max_payload_bytes=None, max_media_bytes=20_000_000, max_media_blocks=20)


def test_unsupported_image_format_raises_error():
    bad = image_payload(format="bmp")
    with pytest.raises(MultimodalPayloadError, match="not supported"):
        parse_payload(bad, max_payload_bytes=None, max_media_bytes=20_000_000, max_media_blocks=20)
```

---

## 4. Session lifecycle tests -- `tests/server/test_session.py`

Fake `load_session` at our seam. Assert on the observable outcome: events placed
on the queue, queue closed, error events on failure.

```python
from __future__ import annotations

import asyncio
from unittest.mock import patch

import pytest

from strands_compose_agentcore.session import resolve_session, run_entry_agent
from tests.fakes.compose import FakeEntry, FakeResolvedConfig


def test_resolve_session_returns_session_state_with_event_queue():
    fake_resolved = FakeResolvedConfig()
    with patch(
        "strands_compose_agentcore.session.load_session",
        return_value=fake_resolved,
    ):
        state = resolve_session(None, None, "a" * 40)

    assert state.events is not None
    assert state.session_id == "a" * 40


async def test_run_entry_agent_closes_queue_on_success():
    entry = FakeEntry(result="done")
    resolved = FakeResolvedConfig(entry=entry)
    events = resolved.wire_event_queue(session_id="test")
    events.flush()

    await run_entry_agent(resolved, events, "Hello")

    # Queue is closed -- get() returns None (sentinel)
    assert await events.get() is None


async def test_run_entry_agent_emits_error_on_timeout():
    entry = FakeEntry(delay=10)  # will exceed timeout
    resolved = FakeResolvedConfig(entry=entry)
    events = resolved.wire_event_queue(session_id="test")
    events.flush()

    await run_entry_agent(resolved, events, "Hello", invocation_timeout=0.01)

    # Drain: should contain an error event before close
    collected = []
    while (ev := await events.get()) is not None:
        collected.append(ev)
    assert any(e.type == "error" for e in collected)
```

---

## 5. App integration test -- `tests/server/test_app.py`

Drive the ASGI app via Starlette TestClient or httpx ASGITransport. Fake the
session resolution seam so no real agents run.

```python
from __future__ import annotations

from unittest.mock import patch

from starlette.testclient import TestClient

from strands_compose_agentcore.app import create_app
from tests.fakes.compose import FakeSessionState


def _make_app():
    """Build an app with faked infrastructure (no real config needed)."""
    with patch("strands_compose_agentcore._utils.prepare_app_state") as mock_prep:
        mock_prep.return_value = (None, None)  # app_config, infra
        with patch("strands_compose_agentcore.app._make_lifespan") as mock_ls:
            # Skip real lifespan -- inject state directly
            from contextlib import asynccontextmanager

            @asynccontextmanager
            async def _noop_lifespan(app):
                app.state.app_config = None
                app.state.infra = None
                app.state.session = None
                yield

            mock_ls.return_value = _noop_lifespan
            app = create_app("dummy")
    return app


def test_invocations_returns_sse_events():
    app = _make_app()
    fake_session = FakeSessionState()
    with patch(
        "strands_compose_agentcore.app.resolve_session",
        return_value=fake_session,
    ):
        client = TestClient(app, raise_server_exceptions=False)
        resp = client.post(
            "/invocations",
            json={"prompt": "Hello"},
            headers={"X-Amzn-Bedrock-AgentCore-Runtime-Session-Id": "a" * 40},
        )
    assert resp.status_code == 200


def test_invocations_rejects_missing_prompt():
    app = _make_app()
    client = TestClient(app, raise_server_exceptions=False)
    resp = client.post(
        "/invocations",
        json={},
        headers={"X-Amzn-Bedrock-AgentCore-Runtime-Session-Id": "a" * 40},
    )
    # Should get an error event in the SSE stream
    assert resp.status_code == 200  # SSE always returns 200
    assert "error" in resp.text
```

---

## 6. Client body assembly -- `tests/client/test_body.py`

Test the public `build_invocation_body` function. Assert on shape, not
internal calls.

```python
from __future__ import annotations

import pytest

from strands_compose_agentcore.client.utils import build_invocation_body


def test_string_produces_prompt_key():
    assert build_invocation_body("Hi") == {"prompt": "Hi"}


def test_single_block_wraps_in_list():
    block = {"text": "Hello"}
    result = build_invocation_body(block)
    assert result == {"prompt": [{"text": "Hello"}]}


def test_list_of_blocks_preserved():
    blocks = [{"text": "a"}, {"text": "b"}]
    result = build_invocation_body(blocks)
    assert result == {"prompt": [{"text": "a"}, {"text": "b"}]}


def test_empty_list_raises_value_error():
    with pytest.raises(ValueError):
        build_invocation_body([])
```

---

## 7. SSE parsing -- `tests/client/test_sse.py`

```python
from __future__ import annotations

from strands_compose_agentcore.client.utils import parse_sse_line


def test_valid_data_line_returns_stream_event():
    event = parse_sse_line('data: {"type": "token", "agent_name": "a", "data": {"text": "hi"}}')
    assert event is not None
    assert event.type == "token"


def test_blank_line_returns_none():
    assert parse_sse_line("") is None


def test_non_json_returns_none():
    assert parse_sse_line("keepalive") is None
    assert parse_sse_line(": comment") is None
```

---

## 8. Error translation -- `tests/client/test_errors.py`

```python
from __future__ import annotations

import pytest

from strands_compose_agentcore.client.utils import translate_error
from strands_compose_agentcore.types import (
    AccessDeniedError,
    AgentCoreClientError,
    SessionNotFoundError,
    ThrottledError,
)


class FakeClientError(Exception):
    def __init__(self, code: str, message: str = "msg"):
        self.response = {"Error": {"Code": code, "Message": message}}


@pytest.mark.parametrize(
    "code,expected_type",
    [
        ("AccessDeniedException", AccessDeniedError),
        ("ThrottlingException", ThrottledError),
        ("ResourceNotFoundException", SessionNotFoundError),
        ("UnknownCode", AgentCoreClientError),
    ],
)
def test_error_code_maps_to_typed_exception(code, expected_type):
    exc = translate_error(FakeClientError(code))
    assert isinstance(exc, expected_type)
```

---

## 9. Media builder tests -- `tests/media/test_builders.py`

```python
from __future__ import annotations

import base64
from pathlib import Path

import pytest

from strands_compose_agentcore.media import document, image, reply, text


def test_text_returns_text_block():
    result = text("hello")
    assert result == {"text": "hello"}


def test_image_from_bytes_requires_format():
    with pytest.raises(ValueError, match="format"):
        image(b"\x89PNG", format=None)


def test_image_from_bytes_with_format():
    result = image(b"\x89PNG\r\n\x1a\n", format="png")
    assert "image" in result
    assert result["image"]["format"] == "png"
    decoded = base64.b64decode(result["image"]["source"]["base64"])
    assert decoded == b"\x89PNG\r\n\x1a\n"


def test_image_from_path_infers_format(tmp_path: Path):
    img_file = tmp_path / "photo.jpeg"
    img_file.write_bytes(b"\xff\xd8\xff\xe0")
    result = image(img_file)
    assert result["image"]["format"] == "jpeg"


def test_document_from_path_generates_name(tmp_path: Path):
    doc_file = tmp_path / "report.pdf"
    doc_file.write_bytes(b"%PDF-1.4")
    result = document(doc_file)
    assert result["document"]["name"].startswith("report-")


def test_reply_shape():
    result = reply("int-1", {"answer": "yes"})
    assert result == {"reply": {"interrupt_id": "int-1", "response": {"answer": "yes"}}}
```

---

## 10. Property tests -- `tests/media/test_formats.py`

```python
from __future__ import annotations

from strands_compose_agentcore.media_formats import MEDIA_FORMATS
from strands_compose_agentcore.types import DOCUMENT_FORMATS, IMAGE_FORMATS


def test_every_format_has_valid_structure():
    for spec in MEDIA_FORMATS:
        assert spec.format, "format token must not be empty"
        assert spec.category in ("image", "document")
        assert spec.extensions, "must have at least one extension"
        assert all(ext.startswith(".") for ext in spec.extensions)
        assert spec.mime_type, "mime_type must not be empty"


def test_image_and_document_sets_are_disjoint():
    assert IMAGE_FORMATS & DOCUMENT_FORMATS == frozenset()


def test_format_sets_cover_all_entries():
    all_formats = {s.format for s in MEDIA_FORMATS}
    assert IMAGE_FORMATS | DOCUMENT_FORMATS == all_formats
```

---

## 11. Session ID validation -- `tests/utils/test_validation.py`

```python
from __future__ import annotations

import pytest

from strands_compose_agentcore._utils import validate_session_id


def test_none_is_accepted():
    validate_session_id(None)  # should not raise


def test_valid_length_accepted():
    validate_session_id("x" * 33)
    validate_session_id("y" * 256)


def test_too_short_raises():
    with pytest.raises(ValueError, match="too short"):
        validate_session_id("x" * 32)


def test_too_long_raises():
    with pytest.raises(ValueError, match="too long"):
        validate_session_id("x" * 257)
```

---

## Quick decision guide

| I'm testing... | Folder | Fake at? | Assert on |
|---------------|--------|----------|-----------|
| payload shape/rejection | `server/` | nothing | decoded value type + structure, or error type |
| session resolution wiring | `server/` | `load_session` | `SessionState` fields, queue open/closed |
| entry agent run + error handling | `server/` | `entry.invoke_async` | events on queue, queue closed |
| app invocation end-to-end | `server/` | `resolve_session` | SSE response contains expected events |
| client body assembly | `client/` | nothing | `{"prompt": ...}` shape |
| SSE line parsing | `client/` | nothing | `StreamEvent` or `None` |
| error code translation | `client/` | nothing | exception type |
| client invoke streaming | `client/` | HTTP transport | yielded `StreamEvent` |
| media builders | `media/` | nothing (use `tmp_path`) | dict shape + format + decoded bytes |
| format registry | `media/` | nothing | invariants (disjoint, complete, valid) |
| session ID validation | `utils/` | nothing | accepted or `ValueError` |
| CLI dispatch | `cli/` | command internals | `CLIError` raised or correct dispatch |
| wire contract shape | `contract/` | nothing | key names (snapshot) |
