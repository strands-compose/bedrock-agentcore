"""Root conftest: markers, shared infrastructure fixtures.

- Registers the ``integration`` marker for slow app-level tests.
- Provides an ``app_builder`` fixture that creates a testable ASGI app
  (patches the lifespan so no real agents are resolved).
- No autouse patches that hide test arrange steps.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import Any
from unittest.mock import patch

import pytest
from starlette.testclient import TestClient

from strands_compose_agentcore.app import create_app
from tests.factories import minimal_app_config


def pytest_configure(config: pytest.Config) -> None:
    """Register custom markers."""
    config.addinivalue_line("markers", "integration: marks slow app-level integration tests")


@pytest.fixture()
def app_builder():
    """Build a testable ASGI app with session resolution faked out.

    Returns a callable that creates the app from a real minimal AppConfig.
    ``_make_lifespan`` is patched so nothing live is built -- suitable for
    testing the invocation entrypoint with faked sessions.
    """

    def _build(**create_app_kwargs: Any):
        with patch("strands_compose_agentcore.app._make_lifespan") as mock_ls:

            @asynccontextmanager
            async def _noop_lifespan(app):
                app.state.app_config = None
                app.state.session = None
                yield

            mock_ls.return_value = _noop_lifespan
            app = create_app(minimal_app_config(), **create_app_kwargs)
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
