"""Root conftest: markers, shared infrastructure fixtures.

- Registers the ``integration`` marker for slow app-level tests.
- Provides an ``app_builder`` fixture that creates a testable ASGI app
  (patches prepare_app_state and lifespan to skip real MCP).
- No autouse patches that hide test arrange steps.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import Any
from unittest.mock import patch

import pytest
from starlette.testclient import TestClient

from strands_compose_agentcore.app import create_app

# prepare_app_state is patched out below; its (app_config, infra) return
# value is forwarded only into the also-patched _make_lifespan, which
# ignores its arguments and always returns _noop_lifespan.  Neither value
# is ever inspected, so plain sentinels make that fact visible instead of
# implying a rich fake is needed.
_APP_CONFIG = object()
_INFRA = object()


def pytest_configure(config: pytest.Config) -> None:
    """Register custom markers."""
    config.addinivalue_line("markers", "integration: marks slow app-level integration tests")


@pytest.fixture()
def app_builder():
    """Build a testable ASGI app with infrastructure faked out.

    Returns a callable that creates the app. The returned app skips
    real MCP lifecycle and infrastructure resolution -- suitable for
    testing the invocation entrypoint with faked sessions.
    """

    def _build(**create_app_kwargs: Any):
        with patch("strands_compose_agentcore.app.prepare_app_state") as mock_prep:
            mock_prep.return_value = (_APP_CONFIG, _INFRA)
            with patch("strands_compose_agentcore.app._make_lifespan") as mock_ls:

                @asynccontextmanager
                async def _noop_lifespan(app):
                    app.state.app_config = None
                    app.state.infra = None
                    app.state.session = None
                    yield

                mock_ls.return_value = _noop_lifespan
                app = create_app("dummy.yaml", **create_app_kwargs)
        return app

    return _build


@pytest.fixture()
def test_client(app_builder):
    """Provide a Starlette TestClient with the faked ASGI app.

    The _noop_lifespan sets app.state attributes during startup.
    No redundant re-initialization here -- if lifespan fails to set
    state, that is a real bug the test should surface.
    """
    app = app_builder()
    with TestClient(app, raise_server_exceptions=False) as client:
        yield client
