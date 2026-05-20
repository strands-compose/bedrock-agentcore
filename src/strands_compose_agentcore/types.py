"""Public types for ``strands_compose_agentcore``.

The client wire contract is intentionally smaller than Strands'
native ``AgentInput`` union.  Application code may send a plain prompt
string, one content block, or a list of content blocks built from
``text()``, ``image()``, ``document()``, and ``reply()``.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal, TypeAlias, TypedDict

__all__ = [
    "AccessDeniedError",
    "AgentCoreClientError",
    "AgentInput",
    "ClientConnectionError",
    "ContentBlock",
    "DOCUMENT_FORMATS",
    "DocumentFormat",
    "DocumentBlock",
    "DocumentContent",
    "IMAGE_FORMATS",
    "ImageFormat",
    "ImageBlock",
    "ImageContent",
    "MediaSource",
    "ReplyBlock",
    "ReplyContent",
    "RetryConfig",
    "TextBlock",
    "ThrottledError",
]


# ---------------------------------------------------------------------------
# Invocation content
# ---------------------------------------------------------------------------


ImageFormat: TypeAlias = Literal["png", "jpeg", "gif", "webp"]
DocumentFormat: TypeAlias = Literal["pdf", "csv", "doc", "docx", "xls", "xlsx", "html", "txt", "md"]

IMAGE_FORMATS: frozenset[str] = frozenset({"png", "jpeg", "gif", "webp"})
DOCUMENT_FORMATS: frozenset[str] = frozenset(
    {"pdf", "csv", "doc", "docx", "xls", "xlsx", "html", "txt", "md"}
)


class MediaSource(TypedDict):
    """Base64-encoded media bytes for the JSON wire contract."""

    base64: str


class TextBlock(TypedDict):
    """Text content sent as part of a multimodal user turn."""

    text: str


class ImageContent(TypedDict):
    """Image content sent as part of a multimodal user turn."""

    format: ImageFormat
    source: MediaSource


class ImageBlock(TypedDict):
    """Image block accepted by ``LocalClient`` and ``AgentCoreClient``."""

    image: ImageContent


class DocumentContent(TypedDict):
    """Document content sent as part of a multimodal user turn."""

    format: DocumentFormat
    name: str
    source: MediaSource


class DocumentBlock(TypedDict):
    """Document block accepted by ``LocalClient`` and ``AgentCoreClient``."""

    document: DocumentContent


class ReplyContent(TypedDict):
    """Human reply to a pending Strands interrupt."""

    interrupt_id: str
    response: Any


class ReplyBlock(TypedDict):
    """Reply block accepted by ``LocalClient`` and ``AgentCoreClient``."""

    reply: ReplyContent


ContentBlock: TypeAlias = TextBlock | ImageBlock | DocumentBlock | ReplyBlock
AgentInput: TypeAlias = str | ContentBlock | list[ContentBlock]


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------


class AgentCoreClientError(Exception):
    """Base exception for all client errors (local and remote)."""


class ClientConnectionError(AgentCoreClientError, ConnectionError):
    """Raised when the client cannot reach the agent server.

    Inherits from both :class:`AgentCoreClientError` and the built-in
    :class:`ConnectionError` so callers can catch either.
    """


class AccessDeniedError(AgentCoreClientError):
    """Raised when AWS credentials lack permission to invoke the agent runtime.

    Actionable: check IAM policy for ``bedrock-agentcore:InvokeAgentRuntime``.
    """


class ThrottledError(AgentCoreClientError):
    """Raised when the request is rate-limited by the service.

    Actionable: implement exponential backoff / retry.
    """


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------


@dataclass
class RetryConfig:
    """Configuration for exponential backoff retry on throttled requests.

    Args:
        max_retries: Maximum number of retry attempts.  0 means no retries.
        base_delay: Initial delay in seconds before the first retry.
        max_delay: Maximum delay in seconds between retries.
        jitter: Whether to add random jitter (0 to base_delay) to each delay.
    """

    max_retries: int = 3
    base_delay: float = 1.0
    max_delay: float = 30.0
    jitter: bool = True
