"""Tests for resolve_session and run_entry_agent."""

from __future__ import annotations

import asyncio
from unittest.mock import patch

import pytest
from strands_compose import EventQueue, StreamEvent

from strands_compose_agentcore.session import resolve_session, run_entry_agent
from tests.fakes.compose import FakeEntry, FakeResolvedConfig

# resolve_session forwards these positionally into the patched load_session
# without inspecting them -- plain sentinels make that "never touched" fact
# visible, rather than implying a rich fake is needed.
_APP_CONFIG = object()
_INFRA = object()


async def _drain(events: EventQueue) -> list[StreamEvent]:
    """Drain the queue to the close sentinel, returning the events seen."""
    collected: list[StreamEvent] = []
    while (evt := await events.get()) is not None:
        collected.append(evt)
    return collected


class TestResolveSession:
    """resolve_session threads the session_id through and wires a real queue."""

    def test_resolve_session_threads_session_id_and_wires_event_queue(self) -> None:
        fake_resolved = FakeResolvedConfig()
        with patch("strands_compose_agentcore.session.load_session", return_value=fake_resolved):
            state = resolve_session(
                _APP_CONFIG,  # ty: ignore[invalid-argument-type]
                _INFRA,  # ty: ignore[invalid-argument-type]
                "session-abc-long-enough-for-validation-33ch",
            )

        assert state.session_id == "session-abc-long-enough-for-validation-33ch"
        assert isinstance(state.events, EventQueue)

    def test_resolve_session_accepts_none_session_id(self) -> None:
        fake_resolved = FakeResolvedConfig()
        with patch("strands_compose_agentcore.session.load_session", return_value=fake_resolved):
            state = resolve_session(
                _APP_CONFIG,  # ty: ignore[invalid-argument-type]
                _INFRA,  # ty: ignore[invalid-argument-type]
                None,
            )

        assert state.session_id is None


class TestRunEntryAgent:
    """run_entry_agent drives the entry agent and manages the queue."""

    async def test_run_entry_agent_closes_queue_on_success(self) -> None:
        entry = FakeEntry(result=None)
        resolved = FakeResolvedConfig(entry=entry)
        events = EventQueue(asyncio.Queue(), session_id=None)

        await run_entry_agent(resolved, events, "Hello")  # ty: ignore[invalid-argument-type]

        collected = await _drain(events)
        # close() emits SESSION_END before the None sentinel, then the queue closes.
        assert any(e.type == "session_end" for e in collected)

    async def test_run_entry_agent_emits_error_event_on_timeout(self) -> None:
        gate = asyncio.Event()  # never set -> the entry never completes on its own
        entry = FakeEntry(gate=gate)
        resolved = FakeResolvedConfig(entry=entry)
        events = EventQueue(asyncio.Queue(), session_id=None)

        await run_entry_agent(resolved, events, "Hello", invocation_timeout=0.01)  # ty: ignore[invalid-argument-type]

        collected = await _drain(events)
        assert any(e.type == "error" for e in collected)

    async def test_run_entry_agent_emits_error_event_on_exception(self) -> None:
        entry = FakeEntry(error=RuntimeError("boom"))
        resolved = FakeResolvedConfig(entry=entry)
        events = EventQueue(asyncio.Queue(), session_id=None)

        await run_entry_agent(resolved, events, "Hello")  # ty: ignore[invalid-argument-type]

        collected = await _drain(events)
        assert any(e.type == "error" for e in collected)

    @pytest.mark.parametrize("bad_timeout", [0, -1, float("nan")])
    async def test_run_entry_agent_rejects_non_positive_timeout(self, bad_timeout: float) -> None:
        resolved = FakeResolvedConfig(entry=FakeEntry())
        events = EventQueue(asyncio.Queue(), session_id=None)

        with pytest.raises(ValueError, match="invocation_timeout"):
            await run_entry_agent(resolved, events, "Hello", invocation_timeout=bad_timeout)  # ty: ignore[invalid-argument-type]
