"""Integration tests for the /invocations endpoint using Starlette TestClient."""

from __future__ import annotations

import asyncio
import json
from unittest.mock import patch

import pytest

from tests.fakes.compose import FakeEntry, FakeResolvedConfig, FakeSessionState


@pytest.mark.integration
class TestInvocationsEndpoint:
    """App-level integration tests for the /invocations entrypoint."""

    def test_invocations_returns_sse_events_for_valid_prompt(self, test_client) -> None:
        fake_entry = FakeEntry(result=None)
        fake_resolved = FakeResolvedConfig(entry=fake_entry)
        fake_session = FakeSessionState(resolved=fake_resolved)

        with patch("strands_compose_agentcore.app.resolve_session", return_value=fake_session):
            response = test_client.post(
                "/invocations",
                json={"prompt": "Hello"},
                headers={"X-Amzn-Bedrock-AgentCore-Runtime-Session-Id": "a" * 33},
            )

        assert response.status_code == 200
        # The response should contain at least one JSON line (events as SSE)
        body = response.text
        assert body  # non-empty

    def test_invocations_returns_error_event_for_missing_prompt(self, test_client) -> None:
        response = test_client.post(
            "/invocations",
            json={},
            headers={"X-Amzn-Bedrock-AgentCore-Runtime-Session-Id": "a" * 33},
        )

        assert response.status_code == 200
        # Should contain an error event
        lines = [line for line in response.text.strip().split("\n") if line.strip()]
        events = []
        for line in lines:
            text = line.strip()
            if text.startswith("data: "):
                text = text[6:]
            try:
                events.append(json.loads(text))
            except json.JSONDecodeError:
                continue
        assert any(e.get("type") == "error" for e in events)

    def test_invocations_rejects_busy_agent_with_error_event(self, test_client) -> None:
        fake_entry = FakeEntry(result=None)
        fake_resolved = FakeResolvedConfig(entry=fake_entry)
        fake_session = FakeSessionState(resolved=fake_resolved)
        # Simulate locked state
        fake_session.invocation_lock = asyncio.Lock()

        # We need to hold the lock to simulate busy
        loop = asyncio.new_event_loop()
        loop.run_until_complete(fake_session.invocation_lock.acquire())
        loop.close()

        with patch("strands_compose_agentcore.app.resolve_session", return_value=fake_session):
            # First set the cached session
            test_client.app.state.session = fake_session
            response = test_client.post(
                "/invocations",
                json={"prompt": "Hello"},
                headers={"X-Amzn-Bedrock-AgentCore-Runtime-Session-Id": fake_session.session_id},
            )

        lines = [line for line in response.text.strip().split("\n") if line.strip()]
        events = []
        for line in lines:
            text = line.strip()
            if text.startswith("data: "):
                text = text[6:]
            try:
                events.append(json.loads(text))
            except json.JSONDecodeError:
                continue
        assert any("already running" in e.get("data", {}).get("text", "") for e in events)

    def test_invocations_caches_session_for_same_session_id(self, test_client) -> None:
        fake_entry = FakeEntry(result=None)
        fake_resolved = FakeResolvedConfig(entry=fake_entry)
        fake_session = FakeSessionState(resolved=fake_resolved)

        with patch(
            "strands_compose_agentcore.app.resolve_session", return_value=fake_session
        ) as mock_resolve:
            response1 = test_client.post(
                "/invocations",
                json={"prompt": "First"},
                headers={"X-Amzn-Bedrock-AgentCore-Runtime-Session-Id": fake_session.session_id},
            )
            response2 = test_client.post(
                "/invocations",
                json={"prompt": "Second"},
                headers={"X-Amzn-Bedrock-AgentCore-Runtime-Session-Id": fake_session.session_id},
            )

        assert response1.status_code == 200
        assert response2.status_code == 200
        # resolve_session should only be called once for the same session_id
        assert mock_resolve.call_count == 1

    def test_invocations_re_resolves_for_new_session_id(self, test_client) -> None:
        fake_entry = FakeEntry(result=None)
        fake_resolved = FakeResolvedConfig(entry=fake_entry)
        session_a = FakeSessionState(resolved=fake_resolved, session_id="a" * 50)
        session_b = FakeSessionState(resolved=fake_resolved, session_id="b" * 50)

        with patch(
            "strands_compose_agentcore.app.resolve_session", side_effect=[session_a, session_b]
        ) as mock_resolve:
            test_client.post(
                "/invocations",
                json={"prompt": "First"},
                headers={"X-Amzn-Bedrock-AgentCore-Runtime-Session-Id": "a" * 50},
            )
            test_client.post(
                "/invocations",
                json={"prompt": "Second"},
                headers={"X-Amzn-Bedrock-AgentCore-Runtime-Session-Id": "b" * 50},
            )

        assert mock_resolve.call_count == 2
