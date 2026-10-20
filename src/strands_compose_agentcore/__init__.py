"""strands-compose-agentcore — toolkit for deploying strands-compose agents on AgentCore.

Install this package and use :func:`create_app` to wrap a strands-compose
YAML config as a ``BedrockAgentCoreApp``, then call ``app.run()`` from
your entry script.  AgentCore Runtime executes that script, so the same
``app.run()`` starts the server locally and in production.

Example::

    from pathlib import Path
    from strands_compose_agentcore import create_app

    app = create_app(Path(__file__).parent / "config.yaml")

    if __name__ == "__main__":
        app.run(port=8080)
"""

from __future__ import annotations

from .app import create_app
from .client import AgentCoreClient, AsyncLocalClient, LocalClient, StopSessionResult
from .media import document, image, reply, text
from .media_formats import MEDIA_FORMATS, MediaFormatSpec
from .types import (
    DOCUMENT_FORMATS,
    IMAGE_FORMATS,
    AccessDeniedError,
    AgentCoreClientError,
    AgentInput,
    ClientConnectionError,
    ConflictError,
    ContentBlock,
    DocumentBlock,
    DocumentFormat,
    ImageBlock,
    ImageFormat,
    InvalidRequestError,
    ReplyBlock,
    RetryableConflictError,
    RetryConfig,
    SessionNotFoundError,
    TextBlock,
    ThrottledError,
)

__all__ = [
    "DOCUMENT_FORMATS",
    "IMAGE_FORMATS",
    "MEDIA_FORMATS",
    "AccessDeniedError",
    "AgentCoreClient",
    "AgentCoreClientError",
    "AgentInput",
    "AsyncLocalClient",
    "ClientConnectionError",
    "ConflictError",
    "ContentBlock",
    "DocumentBlock",
    "DocumentFormat",
    "ImageBlock",
    "ImageFormat",
    "InvalidRequestError",
    "LocalClient",
    "MediaFormatSpec",
    "ReplyBlock",
    "RetryConfig",
    "RetryableConflictError",
    "SessionNotFoundError",
    "StopSessionResult",
    "TextBlock",
    "ThrottledError",
    "create_app",
    "document",
    "image",
    "reply",
    "text",
]
