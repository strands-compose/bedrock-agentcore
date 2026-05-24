"""Shared test fixtures and helpers."""

from __future__ import annotations

from collections.abc import AsyncIterator, Generator
from unittest.mock import MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Factory helpers — used by both test_app.py and test_app_invoke.py
# ---------------------------------------------------------------------------


def make_infra() -> MagicMock:
    """Return a mock ResolvedInfra with an MCP lifecycle stub."""
    infra = MagicMock()
    infra.mcp_lifecycle = MagicMock()
    return infra


def make_app_config() -> MagicMock:
    """Return a mock AppConfig with an entry point."""
    config = MagicMock()
    config.entry = "agent"
    return config


def make_resolved_config(entry: MagicMock | None = None) -> MagicMock:
    """Return a mock ResolvedConfig with agents and an entry point."""
    config = MagicMock()
    config.entry = entry or MagicMock()
    config.agents = {"agent": MagicMock()}
    config.orchestrators = {}
    return config


async def empty_stream(*_args: object, **_kwargs: object) -> AsyncIterator[None]:
    """Async generator that yields nothing — used as a stream_invocation stub."""
    return
    yield  # noqa: RET504


# ---------------------------------------------------------------------------
# Autouse fixture — patches build_manifest for all invoke-path tests
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _patch_build_manifest() -> Generator[MagicMock, None, None]:
    """Patch build_manifest in app.py so MagicMock resolved configs don't fail Pydantic validation."""
    with patch("strands_compose_agentcore.app.build_manifest") as mock:
        mock.return_value = MagicMock()
        yield mock
