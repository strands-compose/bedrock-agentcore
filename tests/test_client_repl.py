"""Tests for AgentCoreClient REPL behavior."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from strands_compose import StreamEvent

from strands_compose_agentcore.client.agentcore import AgentCoreClient

_TEST_ARN = "arn:aws:bedrock-agentcore:us-west-2:123456789012:runtime/test-agent"


def _make_client() -> AgentCoreClient:
    session = MagicMock()
    session.region_name = "us-west-2"
    session.client.return_value = MagicMock()
    return AgentCoreClient(_TEST_ARN, session=session)


class TestAgentCoreClientRepl:
    def test_repl_streams_events_and_flushes_renderer(self) -> None:
        client = _make_client()
        long_id = "a" * 33
        event = StreamEvent(type="token", agent_name="agent", data={"text": "hi"})

        seen: list[tuple[str, str]] = []

        async def _fake_invoke(*, session_id: str, prompt: str):
            seen.append((session_id, prompt))
            yield event

        with (
            patch.object(client, "invoke", side_effect=_fake_invoke),
            patch("strands_compose_agentcore.client.repl.AnsiRenderer") as mock_renderer_cls,
            patch("builtins.input", side_effect=["hello", ""]),
        ):
            renderer = mock_renderer_cls.return_value
            client.repl(session_id=long_id)

        assert seen == [(long_id, "hello")]
        renderer.render.assert_called_once_with(event)
        renderer.flush.assert_called_once()
        client.close()

    def test_repl_rejects_short_session_id(self) -> None:
        client = _make_client()
        with pytest.raises(ValueError, match="too short"):
            client.repl(session_id="short")

    def test_repl_rejects_long_session_id(self) -> None:
        client = _make_client()
        with pytest.raises(ValueError, match="too long"):
            client.repl(session_id="a" * 257)

    def test_repl_generates_default_session_id(self) -> None:
        client = _make_client()

        seen_session_ids: list[str] = []

        async def _fake_invoke(*, session_id: str, prompt: str):
            seen_session_ids.append(session_id)
            yield StreamEvent(type="complete", agent_name="agent", data={})

        with (
            patch.object(client, "invoke", side_effect=_fake_invoke),
            patch("strands_compose_agentcore.client.repl.AnsiRenderer"),
            patch("builtins.input", side_effect=["hello", ""]),
        ):
            client.repl()

        assert len(seen_session_ids) == 1
        assert seen_session_ids[0] == "default-session-strands-compose-agentcore"
        client.close()

    def test_repl_stops_on_eof(self) -> None:
        client = _make_client()

        with (
            patch("strands_compose_agentcore.client.repl.AnsiRenderer"),
            patch("builtins.input", side_effect=EOFError),
            patch.object(client, "invoke") as mock_invoke,
        ):
            client.repl(session_id="a" * 33)

        mock_invoke.assert_not_called()
        client.close()

    def test_repl_handles_keyboard_interrupt(self) -> None:
        client = _make_client()

        with (
            patch("strands_compose_agentcore.client.repl.AnsiRenderer"),
            patch("builtins.input", side_effect=KeyboardInterrupt),
            patch.object(client, "invoke") as mock_invoke,
        ):
            client.repl(session_id="b" * 33)

        mock_invoke.assert_not_called()
        client.close()

    @pytest.mark.asyncio
    async def test_repl_works_from_async_context(self) -> None:
        """Verify repl() does not crash with RuntimeError from an async context."""
        client = _make_client()
        long_id = "a" * 33
        event = StreamEvent(type="complete", agent_name="agent", data={})

        async def _fake_invoke(*, session_id: str, prompt: str):
            yield event

        with (
            patch.object(client, "invoke", side_effect=_fake_invoke),
            patch("strands_compose_agentcore.client.repl.AnsiRenderer"),
            patch("builtins.input", side_effect=["hello", ""]),
        ):
            client.repl(session_id=long_id)

        client.close()
