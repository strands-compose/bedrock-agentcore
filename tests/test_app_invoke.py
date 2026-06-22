"""Tests for app invocation flow and concurrency handling."""

from __future__ import annotations

import asyncio
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from strands.agent import AgentResult
from strands.multiagent import MultiAgentResult, Status
from strands.multiagent.base import NodeResult
from strands.telemetry.metrics import EventLoopMetrics
from strands_compose import EventQueue
from strands_compose.types import EventType

from strands_compose_agentcore.app import create_app
from strands_compose_agentcore.session import SessionState, _session_end_data, run_entry_agent

from .conftest import make_app_config, make_infra, make_resolved_config  # pyrefly: ignore

_MOD_APP = "strands_compose_agentcore.app"
_VALID_SID = "a" * 33  # meets AgentCore 33-char minimum


def _agent_result(text: str) -> AgentResult:
    """Build a minimal AgentResult whose single text block is *text*."""
    return AgentResult(
        stop_reason="end_turn",
        message={"role": "assistant", "content": [{"text": text}]},
        metrics=EventLoopMetrics(),
        state={},
    )


def _multiagent_result(*texts: str) -> MultiAgentResult:
    """Build a MultiAgentResult with one completed agent node per text."""
    results = {
        f"node{i}": NodeResult(result=_agent_result(text), status=Status.COMPLETED)
        for i, text in enumerate(texts)
    }
    return MultiAgentResult(status=Status.COMPLETED, results=results)


async def _fake_run(
    resolved: object,
    events: EventQueue,
    agent_input: object,
    *,
    invocation_timeout: object = None,
) -> None:
    """Fake run_entry_agent that closes the queue immediately (no events)."""
    await events.close()


class TestInvokeSessionHandling:
    @pytest.mark.asyncio
    async def test_resolves_session_on_first_call_with_session_id(self) -> None:
        app = create_app(make_app_config(), make_infra())
        invoke = app.handlers["main"]

        resolved = make_resolved_config()
        events = MagicMock(spec=EventQueue)
        events.flush = MagicMock()
        events.get = AsyncMock(return_value=None)
        events.close = AsyncMock()
        session_state = SessionState(resolved=resolved, events=events, session_id=_VALID_SID)

        app.state.app_config = make_app_config()
        app.state.infra = make_infra()
        app.state.session = None

        with (
            patch(f"{_MOD_APP}.BedrockAgentCoreContext.get_session_id", return_value=_VALID_SID),
            patch(f"{_MOD_APP}.resolve_session", return_value=session_state) as mock_resolve,
            patch(f"{_MOD_APP}.run_entry_agent", new=_fake_run),
        ):
            _ = [item async for item in invoke({"prompt": "hi"})]

        mock_resolve.assert_called_once()
        # resolve_session(app_config, infra, session_id) — session_id is args[2]
        assert mock_resolve.call_args.args[2] == _VALID_SID
        assert app.state.session is session_state

    @pytest.mark.asyncio
    async def test_reuses_session_on_follow_up_call(self) -> None:
        app = create_app(make_app_config(), make_infra())
        invoke = app.handlers["main"]

        resolved = make_resolved_config()
        events = MagicMock(spec=EventQueue)
        events.flush = MagicMock()
        events.get = AsyncMock(return_value=None)
        events.close = AsyncMock()
        session_state = SessionState(resolved=resolved, events=events, session_id=_VALID_SID)

        app.state.app_config = make_app_config()
        app.state.infra = make_infra()
        app.state.session = session_state

        with (
            patch(f"{_MOD_APP}.BedrockAgentCoreContext.get_session_id", return_value=_VALID_SID),
            # Patch the underlying resolver so we can detect a cache miss.
            # On a cache hit, resolve_or_reuse short-circuits and never
            # calls resolve_session.
            patch("strands_compose_agentcore.session.resolve_session") as mock_resolve_session,
            patch(f"{_MOD_APP}.run_entry_agent", new=_fake_run),
        ):
            _ = [item async for item in invoke({"prompt": "follow up"})]

        mock_resolve_session.assert_not_called()
        assert app.state.session is session_state

    @pytest.mark.asyncio
    async def test_resolves_new_session_when_idle_with_different_id(self) -> None:
        app = create_app(make_app_config(), make_infra())
        invoke = app.handlers["main"]

        old_resolved = make_resolved_config()
        old_events = MagicMock(spec=EventQueue)
        old_session = SessionState(resolved=old_resolved, events=old_events, session_id="b" * 33)

        new_resolved = make_resolved_config()
        new_events = MagicMock(spec=EventQueue)
        new_events.flush = MagicMock()
        new_events.get = AsyncMock(return_value=None)
        new_events.close = AsyncMock()
        new_session = SessionState(resolved=new_resolved, events=new_events, session_id="c" * 33)

        app.state.app_config = make_app_config()
        app.state.infra = make_infra()
        app.state.session = old_session

        with (
            patch(f"{_MOD_APP}.BedrockAgentCoreContext.get_session_id", return_value="c" * 33),
            patch(f"{_MOD_APP}.resolve_session", return_value=new_session) as mock_resolve,
            patch(f"{_MOD_APP}.run_entry_agent", new=_fake_run),
        ):
            _ = [item async for item in invoke({"prompt": "hi"})]

        mock_resolve.assert_called_once()
        assert mock_resolve.call_args.args[2] == "c" * 33
        assert app.state.session is new_session


class TestInvokeHappyPath:
    @pytest.mark.asyncio
    async def test_streams_events_from_run_entry_agent(self) -> None:
        app = create_app(make_app_config(), make_infra())
        invoke = app.handlers["main"]

        queue: asyncio.Queue = asyncio.Queue()
        events = EventQueue(queue)

        event1 = MagicMock()
        event1.asdict.return_value = {"type": EventType.TOKEN}
        event2 = MagicMock()
        event2.asdict.return_value = {"type": EventType.AGENT_COMPLETE}

        async def _fake_run_with_events(
            resolved: object,
            evts: EventQueue,
            agent_input: object,
            *,
            invocation_timeout: object = None,
        ) -> None:
            evts.put_event(event1)
            evts.put_event(event2)
            await evts.close()

        resolved = make_resolved_config()
        app.state.app_config = make_app_config()
        app.state.infra = make_infra()
        app.state.session = SessionState(resolved=resolved, events=events, session_id=_VALID_SID)

        with (
            patch(f"{_MOD_APP}.BedrockAgentCoreContext.get_session_id", return_value=_VALID_SID),
            patch(f"{_MOD_APP}.run_entry_agent", new=_fake_run_with_events),
        ):
            results = [item async for item in invoke({"prompt": "hello"})]

        assert results[0]["type"] == EventType.SESSION_START
        assert results[1]["type"] == EventType.TOKEN
        assert results[2]["type"] == EventType.AGENT_COMPLETE
        assert results[3]["type"] == EventType.SESSION_END
        assert len(results) == 4


class TestInvokePromptValidation:
    @pytest.mark.asyncio
    async def test_rejects_missing_prompt(self) -> None:
        app = create_app(make_app_config(), make_infra())
        invoke = app.handlers["main"]

        app.state.app_config = make_app_config()
        app.state.infra = make_infra()
        app.state.session = None

        with patch(f"{_MOD_APP}.BedrockAgentCoreContext.get_session_id", return_value="s"):
            results = [item async for item in invoke({})]

        assert len(results) == 1
        assert results[0]["type"] == "error"
        assert "prompt" in results[0]["data"]["message"]

    @pytest.mark.asyncio
    async def test_rejects_empty_prompt(self) -> None:
        app = create_app(make_app_config(), make_infra())
        invoke = app.handlers["main"]

        app.state.app_config = make_app_config()
        app.state.infra = make_infra()
        app.state.session = None

        with patch(f"{_MOD_APP}.BedrockAgentCoreContext.get_session_id", return_value="s"):
            results = [item async for item in invoke({"prompt": ""})]

        assert len(results) == 1
        assert results[0]["type"] == "error"
        assert "prompt" in results[0]["data"]["message"]


class TestInvokeConcurrencyGuard:
    @pytest.mark.asyncio
    async def test_rejects_concurrent_invocation_while_running(self) -> None:
        app = create_app(make_app_config(), make_infra())
        invoke = app.handlers["main"]

        resolved = make_resolved_config()
        events = MagicMock(spec=EventQueue)
        session_state = SessionState(resolved=resolved, events=events, session_id=_VALID_SID)

        await session_state.invocation_lock.acquire()

        app.state.app_config = make_app_config()
        app.state.infra = make_infra()
        app.state.session = session_state

        with (
            patch(f"{_MOD_APP}.BedrockAgentCoreContext.get_session_id", return_value=_VALID_SID),
            patch(f"{_MOD_APP}.resolve_session") as mock_resolve,
            patch(f"{_MOD_APP}.run_entry_agent") as mock_run,
        ):
            results = [item async for item in invoke({"prompt": "blocked"})]

        mock_resolve.assert_not_called()
        mock_run.assert_not_called()
        assert len(results) == 1
        assert results[0]["type"] == "error"
        assert "already running" in results[0]["data"]["message"]

        session_state.invocation_lock.release()

    @pytest.mark.asyncio
    async def test_tracks_async_task_during_invocation(self) -> None:
        app = create_app(make_app_config(), make_infra())
        invoke = app.handlers["main"]

        queue: asyncio.Queue = asyncio.Queue()
        events = EventQueue(queue)
        resolved = make_resolved_config()
        app.state.app_config = make_app_config()
        app.state.infra = make_infra()
        app.state.session = SessionState(resolved=resolved, events=events, session_id=_VALID_SID)

        with (
            patch(f"{_MOD_APP}.BedrockAgentCoreContext.get_session_id", return_value=_VALID_SID),
            patch(f"{_MOD_APP}.run_entry_agent", new=_fake_run),
            patch.object(app, "add_async_task", wraps=app.add_async_task) as mock_add,
            patch.object(
                app, "complete_async_task", wraps=app.complete_async_task
            ) as mock_complete,
        ):
            _ = [item async for item in invoke({"prompt": "hi"})]

        mock_add.assert_called_once_with("invoke")
        mock_complete.assert_called_once()

    @pytest.mark.asyncio
    async def test_completes_async_task_on_exception(self) -> None:
        app = create_app(make_app_config(), make_infra())
        invoke = app.handlers["main"]

        queue: asyncio.Queue = asyncio.Queue()
        events = EventQueue(queue)
        resolved = make_resolved_config()
        app.state.app_config = make_app_config()
        app.state.infra = make_infra()
        app.state.session = SessionState(resolved=resolved, events=events, session_id=_VALID_SID)

        async def _error_run(
            r: object,
            e: EventQueue,
            p: object,
            *,
            invocation_timeout: object = None,
        ) -> None:
            await e.close()
            raise RuntimeError("boom")

        with (
            patch(f"{_MOD_APP}.BedrockAgentCoreContext.get_session_id", return_value=_VALID_SID),
            patch(f"{_MOD_APP}.run_entry_agent", new=_error_run),
        ):
            with pytest.raises(RuntimeError, match="boom"):
                _ = [item async for item in invoke({"prompt": "hi"})]

        assert not app._active_tasks


class TestInvokeSessionIdValidation:
    @pytest.mark.asyncio
    async def test_rejects_short_session_id(self) -> None:
        app = create_app(make_app_config(), make_infra())
        invoke = app.handlers["main"]

        app.state.app_config = make_app_config()
        app.state.infra = make_infra()
        app.state.session = None

        with patch(f"{_MOD_APP}.BedrockAgentCoreContext.get_session_id", return_value="short"):
            results = [item async for item in invoke({"prompt": "hi"})]

        assert len(results) == 1
        assert results[0]["type"] == "error"
        assert "too short" in results[0]["data"]["message"]

    @pytest.mark.asyncio
    async def test_rejects_long_session_id(self) -> None:
        app = create_app(make_app_config(), make_infra())
        invoke = app.handlers["main"]

        app.state.app_config = make_app_config()
        app.state.infra = make_infra()
        app.state.session = None

        with patch(f"{_MOD_APP}.BedrockAgentCoreContext.get_session_id", return_value="a" * 257):
            results = [item async for item in invoke({"prompt": "hi"})]

        assert len(results) == 1
        assert results[0]["type"] == "error"
        assert "too long" in results[0]["data"]["message"]


class TestInvokeMultimodalPayload:
    @pytest.mark.asyncio
    async def test_content_input_forwarded_as_list(self) -> None:
        app = create_app(make_app_config(), make_infra())
        invoke = app.handlers["main"]

        queue: asyncio.Queue = asyncio.Queue()
        events = EventQueue(queue)
        resolved = make_resolved_config()
        app.state.app_config = make_app_config()
        app.state.infra = make_infra()
        app.state.session = SessionState(resolved=resolved, events=events, session_id=_VALID_SID)

        captured: dict[str, object] = {}

        async def _capture(
            r: object,
            e: EventQueue,
            agent_input: object,
            *,
            invocation_timeout: object = None,
        ) -> None:
            captured["agent_input"] = agent_input
            await e.close()

        with (
            patch(f"{_MOD_APP}.BedrockAgentCoreContext.get_session_id", return_value=_VALID_SID),
            patch(f"{_MOD_APP}.run_entry_agent", new=_capture),
        ):
            _ = [item async for item in invoke({"prompt": [{"text": "hello"}, {"text": "world"}]})]

        assert isinstance(captured["agent_input"], list)
        assert captured["agent_input"] == [{"text": "hello"}, {"text": "world"}]

    @pytest.mark.asyncio
    async def test_messages_input_rejected(self) -> None:
        app = create_app(make_app_config(), make_infra())
        invoke = app.handlers["main"]

        resolved = make_resolved_config()
        queue: asyncio.Queue = asyncio.Queue()
        events = EventQueue(queue)
        app.state.app_config = make_app_config()
        app.state.infra = make_infra()
        app.state.session = SessionState(resolved=resolved, events=events, session_id=_VALID_SID)

        msgs = [{"role": "user", "content": [{"text": "hi"}]}]
        with (
            patch(f"{_MOD_APP}.BedrockAgentCoreContext.get_session_id", return_value=_VALID_SID),
            patch(f"{_MOD_APP}.run_entry_agent") as mock_run,
        ):
            results = [item async for item in invoke({"messages": msgs})]

        mock_run.assert_not_called()
        assert results[0]["type"] == "error"

    @pytest.mark.asyncio
    async def test_payload_too_large_yields_structured_error(self) -> None:
        app = create_app(
            make_app_config(),
            make_infra(),
            max_payload_bytes=10,
        )
        invoke = app.handlers["main"]
        app.state.app_config = make_app_config()
        app.state.infra = make_infra()
        app.state.session = None

        with patch(f"{_MOD_APP}.BedrockAgentCoreContext.get_session_id", return_value=_VALID_SID):
            results = [item async for item in invoke({"prompt": "x" * 200})]

        assert len(results) == 1
        assert results[0]["type"] == "error"
        assert "max_payload_bytes" in results[0]["data"]["message"]

    @pytest.mark.asyncio
    async def test_reply_content_forwarded_as_interrupt_response(self) -> None:
        app = create_app(make_app_config(), make_infra())
        invoke = app.handlers["main"]

        queue: asyncio.Queue = asyncio.Queue()
        events = EventQueue(queue)
        resolved = make_resolved_config()
        app.state.app_config = make_app_config()
        app.state.infra = make_infra()
        app.state.session = SessionState(resolved=resolved, events=events, session_id=_VALID_SID)

        captured: dict[str, object] = {}

        async def _capture(
            r: object,
            e: EventQueue,
            agent_input: object,
            *,
            invocation_timeout: object = None,
        ) -> None:
            captured["agent_input"] = agent_input
            await e.close()

        with (
            patch(f"{_MOD_APP}.BedrockAgentCoreContext.get_session_id", return_value=_VALID_SID),
            patch(f"{_MOD_APP}.run_entry_agent", new=_capture),
        ):
            _ = [
                item
                async for item in invoke(
                    {"prompt": [{"reply": {"interrupt_id": "iid", "response": "yes"}}]}
                )
            ]

        assert captured["agent_input"] == [
            {"interruptResponse": {"interruptId": "iid", "response": "yes"}}
        ]


class TestRunEntryAgent:
    @pytest.mark.asyncio
    async def test_invokes_entry_async_with_input(self) -> None:
        queue: asyncio.Queue = asyncio.Queue()
        resolved = MagicMock()
        captured: list[object] = []

        async def _fake_invoke(agent_input: object) -> None:
            captured.append(agent_input)

        resolved.entry.invoke_async = _fake_invoke
        events = EventQueue(queue)

        await run_entry_agent(resolved, events, "hello")

        assert captured == ["hello"]

    @pytest.mark.asyncio
    async def test_closes_events_in_finally_on_success(self) -> None:
        queue: asyncio.Queue = asyncio.Queue()
        resolved = MagicMock()
        resolved.entry.invoke_async = AsyncMock(return_value=None)
        events = EventQueue(queue)

        await run_entry_agent(resolved, events, "hi")

        # close() emits SESSION_END before the sentinel; drain past it
        while (result := await events.get()) is not None:
            pass
        assert result is None

    @pytest.mark.asyncio
    async def test_emits_internal_error_event(self) -> None:
        queue: asyncio.Queue = asyncio.Queue()
        resolved = MagicMock()
        resolved.entry.invoke_async = AsyncMock(side_effect=RuntimeError("boom"))
        events = EventQueue(queue)

        await run_entry_agent(resolved, events, "hi")

        result = await events.get()
        assert result is not None
        assert result.type == "error"
        assert result.data["message"] == "Internal error during agent invocation"

    @pytest.mark.asyncio
    async def test_closes_events_in_finally_on_exception(self) -> None:
        queue: asyncio.Queue = asyncio.Queue()
        resolved = MagicMock()
        resolved.entry.invoke_async = AsyncMock(side_effect=RuntimeError("boom"))
        events = EventQueue(queue)

        await run_entry_agent(resolved, events, "hi")

        # Drain the error event, then SESSION_END, then sentinel
        err = await events.get()
        assert err is not None
        assert err.type == "error"
        while (sentinel := await events.get()) is not None:
            pass
        assert sentinel is None

    @pytest.mark.asyncio
    async def test_re_raises_cancelled_error(self) -> None:
        queue: asyncio.Queue = asyncio.Queue()
        resolved = MagicMock()
        resolved.entry.invoke_async = AsyncMock(side_effect=asyncio.CancelledError())
        events = EventQueue(queue)

        with pytest.raises(asyncio.CancelledError):
            await run_entry_agent(resolved, events, "hi")

        # events.close() still ran in finally; drain past SESSION_END to sentinel
        while (result := await events.get()) is not None:
            pass
        assert result is None

    @pytest.mark.asyncio
    async def test_raises_value_error_for_zero_timeout(self) -> None:
        resolved = MagicMock()
        events = MagicMock(spec=EventQueue)

        with pytest.raises(ValueError, match="invocation_timeout"):
            await run_entry_agent(resolved, events, "hi", invocation_timeout=0)

        resolved.entry.invoke_async.assert_not_called()

    @pytest.mark.asyncio
    async def test_raises_value_error_for_negative_timeout(self) -> None:
        resolved = MagicMock()
        events = MagicMock(spec=EventQueue)

        with pytest.raises(ValueError, match="invocation_timeout"):
            await run_entry_agent(resolved, events, "hi", invocation_timeout=-1.0)

        resolved.entry.invoke_async.assert_not_called()

    @pytest.mark.asyncio
    async def test_raises_value_error_for_nan_timeout(self) -> None:
        resolved = MagicMock()
        events = MagicMock(spec=EventQueue)

        with pytest.raises(ValueError, match="invocation_timeout"):
            await run_entry_agent(resolved, events, "hi", invocation_timeout=float("nan"))

        resolved.entry.invoke_async.assert_not_called()

    @pytest.mark.asyncio
    async def test_emits_timeout_error_event(self) -> None:
        queue: asyncio.Queue = asyncio.Queue()
        resolved = MagicMock()

        async def _slow_invoke(agent_input: str) -> None:
            await asyncio.sleep(100)

        resolved.entry.invoke_async = _slow_invoke
        events = EventQueue(queue)

        await run_entry_agent(resolved, events, "hi", invocation_timeout=0.01)

        result = await events.get()
        assert result is not None
        assert result.type == "error"
        assert "timed out" in result.data["message"]
        assert "0.01 seconds" in result.data["message"]

    @pytest.mark.asyncio
    async def test_no_timeout_when_none(self) -> None:
        queue: asyncio.Queue = asyncio.Queue()
        resolved = MagicMock()
        resolved.entry.invoke_async = AsyncMock(return_value=None)
        events = EventQueue(queue)

        await run_entry_agent(resolved, events, "hi", invocation_timeout=None)

        # No error event — drain past SESSION_END to sentinel
        while (result := await events.get()) is not None:
            pass
        assert result is None

    @pytest.mark.asyncio
    async def test_session_end_carries_response_payload(self) -> None:
        queue: asyncio.Queue = asyncio.Queue()
        resolved = MagicMock()
        resolved.entry.invoke_async = AsyncMock(return_value=_agent_result("Done."))
        events = EventQueue(queue)

        await run_entry_agent(resolved, events, "hi")

        session_end = await events.get()
        assert session_end is not None
        assert session_end.type == EventType.SESSION_END
        assert session_end.data["text"] == "Done.\n"
        assert session_end.data["result"]["type"] == "agent_result"


class TestSessionEndData:
    """Unit tests for the SESSION_END payload builder."""

    def test_none_returns_empty_uniform_shape(self) -> None:
        assert _session_end_data(None) == {"text": "", "result": {}}

    def test_agent_result_text_and_serialized_result(self) -> None:
        data = _session_end_data(_agent_result("Paris is the capital."))

        assert data["text"] == "Paris is the capital.\n"
        assert data["result"]["type"] == "agent_result"
        assert data["result"]["message"]["content"][0]["text"] == "Paris is the capital."

    def test_multiagent_text_is_last_agent_result(self) -> None:
        data = _session_end_data(_multiagent_result("first node", "final node"))

        assert data["text"] == "final node\n"
        assert data["result"]["type"] == "multiagent_result"

    def test_multiagent_without_agent_results_has_empty_text(self) -> None:
        data = _session_end_data(MultiAgentResult(status=Status.COMPLETED, results={}))

        assert data["text"] == ""
        assert data["result"]["type"] == "multiagent_result"

    @pytest.mark.parametrize(
        "response",
        [
            _agent_result("hello"),
            _multiagent_result("a", "b"),
            MultiAgentResult(status=Status.COMPLETED, results={}),
        ],
    )
    def test_payload_is_json_serializable(self, response: AgentResult | MultiAgentResult) -> None:
        # SESSION_END data is JSON-encoded over SSE, so every value the
        # builder emits must round-trip through json.dumps.
        json.dumps(_session_end_data(response))
