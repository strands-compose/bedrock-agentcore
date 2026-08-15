"""Integration tests for the /invocations entrypoint (Starlette TestClient).

These drive the real ASGI app and fake strands-compose at our own
``resolve_session`` seam, so no real agent, model, or MCP client is built.
"""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import patch

import pytest

from tests.fakes.compose import FakeEntry, FakeResolvedConfig, FakeSessionState

_HEADER = "X-Amzn-Bedrock-AgentCore-Runtime-Session-Id"
_SID = "a" * 40


def _sse_events(response: Any) -> list[dict[str, Any]]:
    """Parse the SSE response body into decoded event dicts."""
    events: list[dict[str, Any]] = []
    for line in response.text.strip().split("\n"):
        text = line.strip()
        if not text:
            continue
        text = text.removeprefix("data: ")
        try:
            events.append(json.loads(text))
        except json.JSONDecodeError:
            continue
    return events


@pytest.mark.integration
class TestInvocationsHappyPath:
    """A valid invocation streams a session_start-led lifecycle and closes."""

    def test_invocations_streams_session_start_and_closes(self, test_client) -> None:
        fake_session = FakeSessionState(resolved=FakeResolvedConfig(entry=FakeEntry(result=None)))

        with patch("strands_compose_agentcore.app.resolve_session", return_value=fake_session):
            response = test_client.post(
                "/invocations",
                json={"prompt": "Hello"},
                headers={_HEADER: _SID},
            )

        assert response.status_code == 200
        types = [e.get("type") for e in _sse_events(response)]
        # Lifecycle contract: the stream opens with session_start and ends with
        # session_end (the queue then drains to the close sentinel).
        assert types[0] == "session_start"
        assert types[-1] == "session_end"


@pytest.mark.integration
class TestInvocationsFaultPaths:
    """Every failure degrades to one error event; the app stays up (200)."""

    def test_invocations_yields_error_event_for_missing_prompt(self, test_client) -> None:
        response = test_client.post("/invocations", json={}, headers={_HEADER: _SID})

        assert response.status_code == 200
        assert any(e.get("type") == "error" for e in _sse_events(response))

    def test_invocations_yields_error_event_for_invalid_session_id(self, test_client) -> None:
        response = test_client.post(
            "/invocations", json={"prompt": "Hello"}, headers={_HEADER: "too-short"}
        )

        assert response.status_code == 200
        assert any(e.get("type") == "error" for e in _sse_events(response))

    def test_invocations_yields_error_event_when_resolve_session_raises(self, test_client) -> None:
        with patch(
            "strands_compose_agentcore.app.resolve_session",
            side_effect=RuntimeError("resolution blew up"),
        ):
            response = test_client.post(
                "/invocations", json={"prompt": "Hello"}, headers={_HEADER: _SID}
            )

        assert response.status_code == 200
        assert any(e.get("type") == "error" for e in _sse_events(response))

    def test_invocations_rejects_busy_session_with_error_event(self, test_client) -> None:
        session = FakeSessionState(resolved=FakeResolvedConfig(entry=FakeEntry()))

        async def _hold_lock() -> None:
            await session.invocation_lock.acquire()

        with patch("strands_compose_agentcore.app.resolve_session", return_value=session):
            # Hold the real lock off-loop and prime the cache so the next
            # request observes a busy session.
            test_client.portal.call(_hold_lock)
            test_client.app.state.session = session
            response = test_client.post(
                "/invocations", json={"prompt": "Hello"}, headers={_HEADER: session.session_id}
            )

        events = _sse_events(response)
        assert any(
            e.get("type") == "error" and e.get("data", {}).get("exception_type") == "AgentBusy"
            for e in events
        )


@pytest.mark.integration
class TestInvocationsSessionCaching:
    """Same session_id reuses cached state; a new session_id re-resolves."""

    def test_invocations_reuses_cached_session_for_same_id(self, test_client) -> None:
        resolutions: list[str | None] = []

        def _counting_resolve(app_config, session_id):
            resolutions.append(session_id)
            return FakeSessionState(
                resolved=FakeResolvedConfig(entry=FakeEntry()), session_id=session_id
            )

        with patch("strands_compose_agentcore.app.resolve_session", side_effect=_counting_resolve):
            test_client.post("/invocations", json={"prompt": "1"}, headers={_HEADER: _SID})
            test_client.post("/invocations", json={"prompt": "2"}, headers={_HEADER: _SID})

        assert resolutions == [_SID]

    def test_invocations_re_resolves_for_new_session_id(self, test_client) -> None:
        resolutions: list[str | None] = []

        def _counting_resolve(app_config, session_id):
            resolutions.append(session_id)
            return FakeSessionState(
                resolved=FakeResolvedConfig(entry=FakeEntry()), session_id=session_id
            )

        with patch("strands_compose_agentcore.app.resolve_session", side_effect=_counting_resolve):
            test_client.post("/invocations", json={"prompt": "1"}, headers={_HEADER: "a" * 40})
            test_client.post("/invocations", json={"prompt": "2"}, headers={_HEADER: "b" * 40})

        assert resolutions == ["a" * 40, "b" * 40]

    def test_invocations_closes_the_replaced_session(self, test_client) -> None:
        # Without this, a delegated agent's MCP subprocess outlives the session
        # it belonged to (it sits in a reference cycle refcounting can't reap).
        sessions = [
            FakeSessionState(resolved=FakeResolvedConfig(entry=FakeEntry()), session_id="a" * 40),
            FakeSessionState(resolved=FakeResolvedConfig(entry=FakeEntry()), session_id="b" * 40),
        ]

        with (
            patch("strands_compose_agentcore.app.resolve_session", side_effect=sessions),
            patch("strands_compose_agentcore.app.close_session") as mock_close,
        ):
            test_client.post("/invocations", json={"prompt": "1"}, headers={_HEADER: "a" * 40})
            test_client.post("/invocations", json={"prompt": "2"}, headers={_HEADER: "b" * 40})

        mock_close.assert_called_once_with(sessions[0])
