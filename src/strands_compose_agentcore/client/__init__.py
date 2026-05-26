"""Client modules for invoking strands-compose-agentcore agents.

Two clients for different use cases:

- :class:`AgentCoreClient` — async boto3 wrapper for invoking **deployed**
  agents on AgentCore Runtime.  Safe for multi-tenant async code.
- :class:`LocalClient` — sync HTTP client for invoking a **local** server
  during development.  Zero extra deps, real-time SSE streaming.

Both clients yield :class:`~strands_compose.StreamEvent` objects and
provide a :meth:`repl` method for interactive terminal use with
:class:`~strands_compose.AnsiRenderer`.
"""

from __future__ import annotations

from ..types import (
    AccessDeniedError,
    AgentCoreClientError,
    ClientConnectionError,
    ConflictError,
    InvalidRequestError,
    RetryableConflictError,
    RetryConfig,
    SessionNotFoundError,
    ThrottledError,
)
from .agentcore import AgentCoreClient, StopSessionResult
from .local import AsyncLocalClient, LocalClient
from .utils import DEFAULT_SESSION_ID

__all__ = [
    "AccessDeniedError",
    "AgentCoreClient",
    "AgentCoreClientError",
    "AsyncLocalClient",
    "ClientConnectionError",
    "ConflictError",
    "DEFAULT_SESSION_ID",
    "InvalidRequestError",
    "LocalClient",
    "RetryableConflictError",
    "RetryConfig",
    "SessionNotFoundError",
    "StopSessionResult",
    "ThrottledError",
]
