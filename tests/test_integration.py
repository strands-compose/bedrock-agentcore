"""Integration test — wires create_app with a minimal AppConfig through Starlette TestClient."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

from starlette.testclient import TestClient
from strands_compose import EventQueue, StreamEvent

from strands_compose_agentcore.app import create_app

from .conftest import make_app_config, make_infra, make_resolved_config

_MOD_APP = "strands_compose_agentcore.app"
_SESSION_HEADER = "X-Amzn-Bedrock-AgentCore-Runtime-Session-Id"


class TestIntegration:
    """End-to-end tests through Starlette's TestClient (no mocked ASGI)."""

    def _create_test_app(self) -> tuple:
        """Build a create_app() instance with MCP lifecycle stubbed."""
        app_config = make_app_config()
        infra = make_infra()
        infra.mcp_lifecycle.__aenter__ = AsyncMock(return_value=None)
        infra.mcp_lifecycle.__aexit__ = AsyncMock(return_value=False)
        report = MagicMock()

        with patch(f"{_MOD_APP}.validate_mcp", AsyncMock(return_value=report)):
            app = create_app(app_config, infra)

        return app, app_config, infra

    def test_ping_returns_healthy(self) -> None:
        app, _, _ = self._create_test_app()
        with TestClient(app) as client:
            resp = client.get("/ping")
            assert resp.status_code == 200

    def test_invoke_missing_prompt_returns_error_event(self) -> None:
        app, _, _ = self._create_test_app()
        with TestClient(app) as client:
            resp = client.post(
                "/invocations",
                json={},
                headers={_SESSION_HEADER: "test-session"},
            )
            assert resp.status_code == 200
            body = resp.text
            assert "error" in body
            assert "prompt" in body

    def test_invoke_happy_path_streams_events(self) -> None:
        app, _, _ = self._create_test_app()
        resolved = make_resolved_config()
        event = StreamEvent(type="token", agent_name="agent", data={"text": "hi"})
        mock_queue = MagicMock(spec=EventQueue)

        session_id = "test-session-42-abcdef-0123456789ab"

        with (
            TestClient(app) as client,
            patch(
                f"{_MOD_APP}.resolve_session",
            ) as mock_resolve,
            patch(f"{_MOD_APP}.stream_invocation") as mock_stream,
        ):
            from strands_compose_agentcore.session import SessionState

            mock_resolve.return_value = SessionState(resolved=resolved, events=mock_queue)

            async def _fake_stream(r, e, p, **kwargs):
                yield event

            mock_stream.side_effect = _fake_stream

            resp = client.post(
                "/invocations",
                json={"prompt": "hello"},
                headers={_SESSION_HEADER: session_id},
            )

        assert resp.status_code == 200
        events = []
        for line in resp.text.strip().split("\n"):
            line = line.strip()
            if line.startswith("data: "):
                line = line[len("data: ") :]
            if line:
                try:
                    events.append(json.loads(line))
                except json.JSONDecodeError:
                    pass
        assert any(e.get("type") == "token" for e in events)
