"""Tests for app factory and lifespan."""

from __future__ import annotations

import logging
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from starlette.routing import Route

from strands_compose_agentcore.app import _make_lifespan, create_app
from strands_compose_agentcore.session import resolve_session

from .conftest import make_app_config, make_infra, make_resolved_config  # pyrefly: ignore

_MOD_APP = "strands_compose_agentcore.app"
_MOD_SESSION = "strands_compose_agentcore.session"


class TestMakeLifespan:
    @pytest.mark.asyncio
    async def test_enters_mcp_lifecycle_and_validates(self) -> None:
        infra = MagicMock()
        infra.mcp_lifecycle.__aenter__ = AsyncMock(return_value=None)
        infra.mcp_lifecycle.__aexit__ = AsyncMock(return_value=False)
        app_config = make_app_config()
        report = MagicMock()

        with patch(f"{_MOD_APP}.validate_mcp", AsyncMock(return_value=report)):
            mock_app = MagicMock()
            async with _make_lifespan(app_config, infra)(mock_app):
                pass

        infra.mcp_lifecycle.__aenter__.assert_called_once()
        report.print_summary.assert_called_once()
        assert mock_app.state.app_config is app_config
        assert mock_app.state.infra is infra
        assert mock_app.state.session is None

    @pytest.mark.asyncio
    async def test_session_not_resolved_in_lifespan(self) -> None:
        infra = MagicMock()
        infra.mcp_lifecycle.__aenter__ = AsyncMock(return_value=None)
        infra.mcp_lifecycle.__aexit__ = AsyncMock(return_value=False)

        with (
            patch(f"{_MOD_APP}.validate_mcp", AsyncMock(return_value=MagicMock())),
            patch(f"{_MOD_SESSION}.load_session") as mock_load,
        ):
            mock_app = MagicMock()
            async with _make_lifespan(make_app_config(), infra)(mock_app):
                pass

        mock_load.assert_not_called()


class TestCreateApp:
    def test_returns_bedrock_agentcore_app(self) -> None:
        from bedrock_agentcore import BedrockAgentCoreApp

        app = create_app(make_app_config(), make_infra())
        assert isinstance(app, BedrockAgentCoreApp)

    def test_no_viewer_route_registered(self) -> None:
        app = create_app(make_app_config(), make_infra())
        paths = [r.path for r in app.routes if isinstance(r, Route)]
        assert "/" not in paths

    def test_invoke_registered_as_entrypoint(self) -> None:
        app = create_app(make_app_config(), make_infra())
        assert "main" in app.handlers

    def test_cors_middleware_added_when_origins_provided(self) -> None:
        from starlette.middleware.cors import CORSMiddleware

        app = create_app(
            make_app_config(),
            make_infra(),
            cors_origins=["http://localhost:3000"],
        )
        middleware_classes = [m.cls for m in app.user_middleware]
        assert CORSMiddleware in middleware_classes

    def test_no_cors_middleware_without_origins(self) -> None:
        app = create_app(make_app_config(), make_infra())
        assert len(app.user_middleware) == 0

    def test_suppress_runtime_logging_clears_handlers(self) -> None:
        create_app(
            make_app_config(),
            make_infra(),
            suppress_runtime_logging=True,
        )
        runtime_logger = logging.getLogger("bedrock_agentcore.app")
        assert runtime_logger.handlers == []

    def test_raises_value_error_when_entry_missing(self) -> None:
        config = MagicMock()
        config.entry = None
        with pytest.raises(ValueError, match="entry"):
            create_app(config, make_infra())


class TestResolveSession:
    def test_calls_load_session_with_session_id(self) -> None:
        resolved = make_resolved_config()
        events = MagicMock()
        resolved.wire_event_queue = MagicMock(return_value=events)

        with patch(f"{_MOD_SESSION}.load_session", return_value=resolved) as mock_load:
            state = resolve_session(make_app_config(), make_infra(), "session-42")

        mock_load.assert_called_once()
        call_kwargs = mock_load.call_args
        assert call_kwargs.kwargs.get("session_id") == "session-42"
        assert state.resolved is resolved
        assert state.events is events

    def test_calls_load_session_with_none_session_id(self) -> None:
        resolved = make_resolved_config()
        resolved.wire_event_queue = MagicMock(return_value=MagicMock())

        with patch(f"{_MOD_SESSION}.load_session", return_value=resolved) as mock_load:
            resolve_session(make_app_config(), make_infra(), None)

        assert mock_load.call_args.kwargs.get("session_id") is None
