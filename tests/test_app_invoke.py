"""Tests for app invocation flow and concurrency handling."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from strands_compose import EventQueue

from strands_compose_agentcore.app import create_app
from strands_compose_agentcore.session import SessionState

from .conftest import empty_stream, make_app_config, make_infra, make_resolved_config

_MOD_APP = "strands_compose_agentcore.app"
_VALID_SID = "a" * 33  # meets AgentCore 33-char minimum


class TestInvokeSessionHandling:
    @pytest.mark.asyncio
    async def test_resolves_session_on_first_call_with_session_id(self) -> None:
        app = create_app(make_app_config(), make_infra())
        invoke = app.handlers["main"]

        resolved = make_resolved_config()
        events = MagicMock(spec=EventQueue)
        session_state = SessionState(resolved=resolved, events=events)

        app.state.app_config = make_app_config()
        app.state.infra = make_infra()
        app.state.session = None
        app.state.session_id = None

        with (
            patch(f"{_MOD_APP}.BedrockAgentCoreContext.get_session_id", return_value=_VALID_SID),
            patch(f"{_MOD_APP}.resolve_session", return_value=session_state) as mock_resolve,
            patch(f"{_MOD_APP}.stream_invocation", side_effect=empty_stream),
        ):
            _ = [item async for item in invoke({"prompt": "hi"})]

        mock_resolve.assert_called_once()
        assert mock_resolve.call_args.args[2] == _VALID_SID

    @pytest.mark.asyncio
    async def test_reuses_session_on_follow_up_call(self) -> None:
        app = create_app(make_app_config(), make_infra())
        invoke = app.handlers["main"]

        resolved = make_resolved_config()
        events = MagicMock(spec=EventQueue)
        session_state = SessionState(resolved=resolved, events=events)

        app.state.app_config = make_app_config()
        app.state.infra = make_infra()
        app.state.session = session_state
        app.state.session_id = _VALID_SID

        with (
            patch(f"{_MOD_APP}.BedrockAgentCoreContext.get_session_id", return_value=_VALID_SID),
            patch(f"{_MOD_APP}.resolve_session") as mock_resolve,
            patch(f"{_MOD_APP}.stream_invocation", side_effect=empty_stream),
        ):
            _ = [item async for item in invoke({"prompt": "follow up"})]

        mock_resolve.assert_not_called()

    @pytest.mark.asyncio
    async def test_resolves_new_session_when_idle_with_different_id(self) -> None:
        app = create_app(make_app_config(), make_infra())
        invoke = app.handlers["main"]

        old_resolved = make_resolved_config()
        old_events = MagicMock(spec=EventQueue)
        old_session = SessionState(resolved=old_resolved, events=old_events)

        new_resolved = make_resolved_config()
        new_events = MagicMock(spec=EventQueue)
        new_session = SessionState(resolved=new_resolved, events=new_events)

        app.state.app_config = make_app_config()
        app.state.infra = make_infra()
        app.state.session = old_session
        app.state.session_id = "b" * 33

        with (
            patch(f"{_MOD_APP}.BedrockAgentCoreContext.get_session_id", return_value="c" * 33),
            patch(f"{_MOD_APP}.resolve_session", return_value=new_session) as mock_resolve,
            patch(f"{_MOD_APP}.stream_invocation", side_effect=empty_stream),
        ):
            _ = [item async for item in invoke({"prompt": "hi"})]

        mock_resolve.assert_called_once()
        assert app.state.session is new_session
        assert app.state.session_id == "c" * 33

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
        app.state.session_id = "d" * 33

        with (
            patch(f"{_MOD_APP}.BedrockAgentCoreContext.get_session_id", return_value="e" * 33),
            patch(f"{_MOD_APP}.resolve_session", return_value=session_state),
        ):
            results = [item async for item in invoke({"prompt": "hi"})]

        assert len(results) == 1
        assert results[0]["type"] == "error"
        assert "already running" in results[0]["data"]["message"]

        session_state.invocation_lock.release()


class TestInvokeHappyPath:
    @pytest.mark.asyncio
    async def test_delegates_to_stream_invocation(self) -> None:
        app = create_app(make_app_config(), make_infra())
        invoke = app.handlers["main"]

        event1 = MagicMock()
        event1.asdict.return_value = {"type": "TOKEN"}
        event2 = MagicMock()
        event2.asdict.return_value = {"type": "COMPLETE"}

        async def _fake_stream(resolved, events, prompt, **kwargs):
            for item in [event1, event2]:
                yield item

        resolved = make_resolved_config()
        events = MagicMock(spec=EventQueue)
        app.state.app_config = make_app_config()
        app.state.infra = make_infra()
        app.state.session = SessionState(resolved=resolved, events=events)
        app.state.session_id = _VALID_SID

        with (
            patch(f"{_MOD_APP}.BedrockAgentCoreContext.get_session_id", return_value=_VALID_SID),
            patch(f"{_MOD_APP}.stream_invocation", side_effect=_fake_stream),
        ):
            results = [item async for item in invoke({"prompt": "hello"})]

        assert results == [{"type": "TOKEN"}, {"type": "COMPLETE"}]


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
        session_state = SessionState(resolved=resolved, events=events)

        await session_state.invocation_lock.acquire()

        app.state.app_config = make_app_config()
        app.state.infra = make_infra()
        app.state.session = session_state
        app.state.session_id = _VALID_SID

        with (
            patch(f"{_MOD_APP}.BedrockAgentCoreContext.get_session_id", return_value=_VALID_SID),
            patch(f"{_MOD_APP}.stream_invocation") as mock_stream,
        ):
            results = [item async for item in invoke({"prompt": "blocked"})]

        mock_stream.assert_not_called()
        assert len(results) == 1
        assert results[0]["type"] == "error"
        assert "already running" in results[0]["data"]["message"]

        session_state.invocation_lock.release()

    @pytest.mark.asyncio
    async def test_tracks_async_task_during_invocation(self) -> None:
        app = create_app(make_app_config(), make_infra())
        invoke = app.handlers["main"]

        resolved = make_resolved_config()
        events = MagicMock(spec=EventQueue)
        app.state.app_config = make_app_config()
        app.state.infra = make_infra()
        app.state.session = SessionState(resolved=resolved, events=events)
        app.state.session_id = _VALID_SID

        with (
            patch(f"{_MOD_APP}.BedrockAgentCoreContext.get_session_id", return_value=_VALID_SID),
            patch(f"{_MOD_APP}.stream_invocation", side_effect=empty_stream),
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

        resolved = make_resolved_config()
        events = MagicMock(spec=EventQueue)
        app.state.app_config = make_app_config()
        app.state.infra = make_infra()
        app.state.session = SessionState(resolved=resolved, events=events)
        app.state.session_id = _VALID_SID

        async def _error_stream(r, e, p, **kwargs):
            yield MagicMock(asdict=MagicMock(return_value={"type": "TOKEN"}))
            raise RuntimeError("boom")

        with (
            patch(f"{_MOD_APP}.BedrockAgentCoreContext.get_session_id", return_value=_VALID_SID),
            patch(f"{_MOD_APP}.stream_invocation", side_effect=_error_stream),
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
        app.state.session_id = None

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
        app.state.session_id = None

        with patch(f"{_MOD_APP}.BedrockAgentCoreContext.get_session_id", return_value="a" * 257):
            results = [item async for item in invoke({"prompt": "hi"})]

        assert len(results) == 1
        assert results[0]["type"] == "error"
        assert "too long" in results[0]["data"]["message"]
