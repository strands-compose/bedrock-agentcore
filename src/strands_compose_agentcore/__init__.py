"""strands-compose-agentcore — toolkit for deploying strands-compose agents on AgentCore.

Install this package and use :func:`create_app` to wrap a strands-compose
YAML config as a ``BedrockAgentCoreApp``.  Assign the result to a
module-level ``app`` in your entry script for ``agentcore deploy`` to
discover, or call ``app.run()`` for local development.

Example::

    from pathlib import Path

    from strands_compose_agentcore import create_app

    app = create_app(Path(__file__).parent / "config.yaml")
"""

from __future__ import annotations

from .app import create_app
from .client import (
    AccessDeniedError,
    AgentCoreClient,
    AgentCoreClientError,
    ClientConnectionError,
    LocalClient,
    RetryConfig,
    ThrottledError,
)

__all__ = [
    "AccessDeniedError",
    "AgentCoreClient",
    "AgentCoreClientError",
    "ClientConnectionError",
    "LocalClient",
    "RetryConfig",
    "ThrottledError",
    "create_app",
]
