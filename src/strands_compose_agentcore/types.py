"""Public types for ``strands_compose_agentcore``.

The client wire contract is intentionally smaller than Strands'
native ``AgentInput`` union.  Application code may send a plain prompt
string, one content block, or a list of content blocks built from
``text()``, ``image()``, ``document()``, and ``reply()``.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal, TypeAlias, TypedDict

from .media_formats import MEDIA_FORMATS

__all__ = [
    "AccessDeniedError",
    "AgentCoreClientError",
    "AgentInput",
    "ClientConnectionError",
    "ConflictError",
    "ContentBlock",
    "DOCUMENT_FORMATS",
    "DocumentFormat",
    "DocumentBlock",
    "DocumentContent",
    "IMAGE_FORMATS",
    "ImageFormat",
    "ImageBlock",
    "ImageContent",
    "InvalidRequestError",
    "MediaSource",
    "ReplyBlock",
    "ReplyContent",
    "RetryableConflictError",
    "RetryConfig",
    "SessionNotFoundError",
    "TextBlock",
    "ThrottledError",
]


# ---------------------------------------------------------------------------
# Invocation content
# ---------------------------------------------------------------------------


ImageFormat: TypeAlias = Literal["png", "jpeg", "gif", "webp"]
DocumentFormat: TypeAlias = Literal["pdf", "csv", "doc", "docx", "xls", "xlsx", "html", "txt", "md"]

IMAGE_FORMATS: frozenset[str] = frozenset(s.format for s in MEDIA_FORMATS if s.category == "image")
DOCUMENT_FORMATS: frozenset[str] = frozenset(
    s.format for s in MEDIA_FORMATS if s.category == "document"
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


class SessionNotFoundError(AgentCoreClientError):
    """Raised when the target session is not found or already terminated.

    Maps to the AWS ``ResourceNotFoundException`` error code returned by
    ``StopRuntimeSession`` when the specified session does not exist or has
    already been terminated.  Callers SHOULD treat this as "already stopped,
    no further action needed".
    """


class InvalidRequestError(AgentCoreClientError):
    """Raised when the request contains an invalid parameter.

    Maps to the AWS ``ValidationException`` error code returned by
    ``StopRuntimeSession`` when the agent runtime ARN, session ID, or client
    token fails service-side validation.
    """


class ConflictError(AgentCoreClientError):
    """Raised when the session is in an incompatible state for the operation.

    Maps to the AWS ``ConflictException`` error code returned by
    ``StopRuntimeSession``.  Callers that also want to handle the retryable
    variant should catch :class:`RetryableConflictError` (a subclass) or this
    base class to cover both.
    """


class RetryableConflictError(ConflictError):
    """Raised when a transient conflict can be resolved by retrying.

    Maps to the AWS ``RetryableConflictException`` error code returned by
    ``StopRuntimeSession``.  AWS explicitly signals that the caller MAY retry
    with exponential backoff.  Inherits from :class:`ConflictError` so an
    ``except ConflictError`` block catches both variants.
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
