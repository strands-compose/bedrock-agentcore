"""Integration test — wires create_app with a minimal AppConfig through Starlette TestClient."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

from starlette.testclient import TestClient

from strands_compose_agentcore.app import create_app

from .conftest import make_app_config, make_infra  # pyrefly: ignore

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
