"""Tests for resolve_session, close_session, and run_entry_agent."""

from __future__ import annotations

import asyncio
from unittest.mock import Mock, patch

import pytest
from strands import Agent
from strands.agent import AgentResult
from strands_compose import EventQueue, StreamEvent

from strands_compose_agentcore.session import close_session, resolve_session, run_entry_agent
from tests.factories import minimal_manifest
from tests.fakes.compose import FakeEntry, FakeResolvedConfig, FakeSessionState

# resolve_session forwards this into the patched load without inspecting it --
# a plain sentinel makes that "never touched" fact visible, rather than
# implying a rich fake is needed.
_APP_CONFIG = object()


async def _drain(events: EventQueue) -> list[StreamEvent]:
    """Drain the queue to the close sentinel, returning the events seen."""
    collected: list[StreamEvent] = []
    while (evt := await events.get()) is not None:
        collected.append(evt)
    return collected


class TestResolveSession:
    """resolve_session threads the session_id through and wires a real queue."""

    def test_resolve_session_threads_session_id_and_wires_event_queue(self) -> None:
        # build_manifest is a real strands-compose function needing real
        # resolved agents, so it is patched at our seam.
        with (
            patch("strands_compose_agentcore.session.load", return_value=FakeResolvedConfig()),
            patch(
                "strands_compose_agentcore.session.build_manifest",
                return_value=minimal_manifest(),
            ),
        ):
            state = resolve_session(
                _APP_CONFIG,  # ty: ignore[invalid-argument-type]
                "session-abc-long-enough-for-validation-33ch",
            )

        assert state.session_id == "session-abc-long-enough-for-validation-33ch"
        assert isinstance(state.events, EventQueue)

    def test_resolve_session_accepts_none_session_id(self) -> None:
        with (
            patch("strands_compose_agentcore.session.load", return_value=FakeResolvedConfig()),
            patch(
                "strands_compose_agentcore.session.build_manifest",
                return_value=minimal_manifest(),
            ),
        ):
            state = resolve_session(
                _APP_CONFIG,  # ty: ignore[invalid-argument-type]
                None,
            )

        assert state.session_id is None


class TestCloseSession:
    """close_session releases every agent so MCP clients are not left running."""

    def test_close_session_cleans_up_every_agent(self) -> None:
        first, second = Mock(spec=Agent), Mock(spec=Agent)
        state = FakeSessionState(
            resolved=FakeResolvedConfig(agents={"a": first, "b": second}),
        )

        close_session(state)  # ty: ignore[invalid-argument-type]

        first.cleanup.assert_called_once()
        second.cleanup.assert_called_once()

    def test_close_session_continues_after_a_failing_agent(self) -> None:
        failing = Mock(spec=Agent)
        failing.cleanup.side_effect = RuntimeError("boom")
        healthy = Mock(spec=Agent)
        state = FakeSessionState(
            resolved=FakeResolvedConfig(agents={"bad": failing, "good": healthy}),
        )

        close_session(state)  # ty: ignore[invalid-argument-type]

        healthy.cleanup.assert_called_once()

    def test_close_session_cleans_up_a_delegate_orchestrator(self) -> None:
        # A delegate orchestration is an Agent holding the same MCP clients as
        # its entry agent, but it never appears in resolved.agents.
        forked = Mock(spec=Agent)
        state = FakeSessionState(
            resolved=FakeResolvedConfig(orchestrators={"coord": forked}),
        )

        close_session(state)  # ty: ignore[invalid-argument-type]

        forked.cleanup.assert_called_once()

    def test_close_session_skips_non_agent_orchestrators(self) -> None:
        # A Swarm/Graph is not an Agent; its nodes are the agents already
        # covered by resolved.agents.
        node = Mock(spec=Agent)
        state = FakeSessionState(
            resolved=FakeResolvedConfig(
                agents={"a": node},
                orchestrators={"team": object()},  # stands in for a Swarm
            ),
        )

        close_session(state)  # ty: ignore[invalid-argument-type]

        node.cleanup.assert_called_once()


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

    async def test_run_entry_agent_closes_the_queue_when_cancelled(self) -> None:
        # What the entrypoint does when the consumer disconnects mid-stream: it
        # cancels the run task.  CancelledError must propagate, and the queue
        # must still close so nothing is left waiting on it.
        gate = asyncio.Event()  # never set -> only cancellation ends this run
        events = EventQueue(asyncio.Queue(), session_id=None)
        resolved = FakeResolvedConfig(entry=FakeEntry(gate=gate))

        task = asyncio.create_task(
            run_entry_agent(resolved, events, "Hello")  # ty: ignore[invalid-argument-type]
        )
        await asyncio.sleep(0)  # let the run reach the gate
        task.cancel()

        with pytest.raises(asyncio.CancelledError):
            await task

        collected = await _drain(events)
        assert any(e.type == "session_end" for e in collected)

    @pytest.mark.parametrize("bad_timeout", [0, -1, float("nan")])
    async def test_run_entry_agent_rejects_non_positive_timeout(self, bad_timeout: float) -> None:
        resolved = FakeResolvedConfig(entry=FakeEntry())
        events = EventQueue(asyncio.Queue(), session_id=None)

        with pytest.raises(ValueError, match="invocation_timeout"):
            await run_entry_agent(resolved, events, "Hello", invocation_timeout=bad_timeout)  # ty: ignore[invalid-argument-type]


class TestSessionEndPayload:
    """The SESSION_END event carries the entry node's final response."""

    async def _session_end(self, result: object) -> dict:
        events = EventQueue(asyncio.Queue(), session_id=None)
        resolved = FakeResolvedConfig(entry=FakeEntry(result=result))

        await run_entry_agent(resolved, events, "Hello")  # ty: ignore[invalid-argument-type]

        collected = await _drain(events)
        return next(e.data for e in collected if e.type == "session_end")

    async def test_agent_result_reports_its_text_and_full_dict(self) -> None:
        agent_result = Mock(spec=AgentResult)
        agent_result.__str__ = Mock(return_value="the answer")
        agent_result.to_dict.return_value = {"type": "agent_result"}

        data = await self._session_end(agent_result)

        assert data["text"] == "the answer"
        assert data["result"] == {"type": "agent_result"}

    async def test_failed_invocation_reports_an_empty_response(self) -> None:
        events = EventQueue(asyncio.Queue(), session_id=None)
        resolved = FakeResolvedConfig(entry=FakeEntry(error=RuntimeError("boom")))

        await run_entry_agent(resolved, events, "Hello")  # ty: ignore[invalid-argument-type]

        collected = await _drain(events)
        data = next(e.data for e in collected if e.type == "session_end")
        assert (data["text"], data["result"]) == ("", {})
