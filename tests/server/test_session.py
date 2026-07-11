"""Tests for resolve_session and run_entry_agent."""

from __future__ import annotations

import asyncio
from unittest.mock import patch

import pytest
from strands_compose import EventQueue, StreamEvent

from strands_compose_agentcore.session import resolve_session, run_entry_agent
from tests.fakes.compose import FakeEntry, FakeResolvedConfig


class TestResolveSession:
    """resolve_session returns SessionState with correct fields."""

    def test_resolve_session_returns_state_with_correct_session_id(self) -> None:
        fake_resolved = FakeResolvedConfig()
        with patch("strands_compose_agentcore.session.load_session", return_value=fake_resolved):
            from unittest.mock import MagicMock

            app_config = MagicMock()
            infra = MagicMock()
            state = resolve_session(
                app_config, infra, "session-abc-long-enough-for-validation-33ch"
            )
            assert state.session_id == "session-abc-long-enough-for-validation-33ch"

    def test_resolve_session_returns_state_with_event_queue(self) -> None:
        fake_resolved = FakeResolvedConfig()
        with patch("strands_compose_agentcore.session.load_session", return_value=fake_resolved):
            from unittest.mock import MagicMock

            state = resolve_session(MagicMock(), MagicMock(), None)
            assert isinstance(state.events, EventQueue)

    def test_resolve_session_accepts_none_session_id(self) -> None:
        fake_resolved = FakeResolvedConfig()
        with patch("strands_compose_agentcore.session.load_session", return_value=fake_resolved):
            from unittest.mock import MagicMock

            state = resolve_session(MagicMock(), MagicMock(), None)
            assert state.session_id is None


class TestRunEntryAgent:
    """run_entry_agent drives the entry agent and manages the queue."""

    async def test_run_entry_agent_closes_queue_on_success(self) -> None:
        entry = FakeEntry(result=None)
        resolved = FakeResolvedConfig(entry=entry)
        events = EventQueue(asyncio.Queue(), session_id=None)

        await run_entry_agent(resolved, events, "Hello")  # ty: ignore[invalid-argument-type]

        # Queue should be closed: drain until sentinel None is reached
        collected: list[StreamEvent] = []
        while (evt := await events.get()) is not None:
            collected.append(evt)
        # The close emits SESSION_END before the None sentinel
        assert any(e.type == "session_end" for e in collected)

    async def test_run_entry_agent_emits_error_event_on_timeout(self) -> None:
        entry = FakeEntry(delay=5.0)
        resolved = FakeResolvedConfig(entry=entry)
        events = EventQueue(asyncio.Queue(), session_id=None)

        await run_entry_agent(resolved, events, "Hello", invocation_timeout=0.01)  # ty: ignore[invalid-argument-type]

        # Should have emitted an error event before the sentinel
        collected: list[StreamEvent] = []
        while (evt := await events.get()) is not None:
            collected.append(evt)
        assert any(e.type == "error" for e in collected)

    async def test_run_entry_agent_emits_error_event_on_exception(self) -> None:
        entry = FakeEntry(error=RuntimeError("boom"))
        resolved = FakeResolvedConfig(entry=entry)
        events = EventQueue(asyncio.Queue(), session_id=None)

        await run_entry_agent(resolved, events, "Hello")  # ty: ignore[invalid-argument-type]

        collected: list[StreamEvent] = []
        while (evt := await events.get()) is not None:
            collected.append(evt)
        assert any(e.type == "error" for e in collected)

    @pytest.mark.parametrize("timeout", [0, -1])
    async def test_run_entry_agent_raises_for_invalid_timeout(self, timeout: float) -> None:
        entry = FakeEntry()
        resolved = FakeResolvedConfig(entry=entry)
        events = EventQueue(asyncio.Queue(), session_id=None)

        with pytest.raises(ValueError, match="positive"):
            await run_entry_agent(resolved, events, "Hello", invocation_timeout=timeout)  # ty: ignore[invalid-argument-type]

    async def test_run_entry_agent_raises_for_nan_timeout(self) -> None:
        entry = FakeEntry()
        resolved = FakeResolvedConfig(entry=entry)
        events = EventQueue(asyncio.Queue(), session_id=None)

        with pytest.raises(ValueError, match="positive"):
            await run_entry_agent(resolved, events, "Hello", invocation_timeout=float("nan"))  # ty: ignore[invalid-argument-type]
