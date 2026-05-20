"""Shared client utilities: SSE parsing and exception types."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Any

from strands_compose import StreamEvent

logger = logging.getLogger(__name__)

__all__ = [
    "AccessDeniedError",
    "AgentCoreClientError",
    "ClientConnectionError",
    "DEFAULT_SESSION_ID",
    "RetryConfig",
    "ThrottledError",
    "build_invocation_body",
    "parse_sse_line",
    "translate_error",
]

# ---------------------------------------------------------------------------
# Session ID default
# ---------------------------------------------------------------------------

DEFAULT_SESSION_ID = "default-session-strands-compose-agentcore"

# ---------------------------------------------------------------------------
# SSE parsing
# ---------------------------------------------------------------------------

_SSE_DATA_PREFIX = "data: "


def parse_sse_line(text: str) -> StreamEvent | None:
    """Parse a single SSE line into a StreamEvent.

    Strips the ``data: `` prefix if present, decodes the JSON payload,
    and returns a :class:`~strands_compose.StreamEvent`.  Returns
    ``None`` for blank lines, non-JSON content, and other noise.

    Args:
        text: Raw SSE line (already decoded and stripped).

    Returns:
        Parsed StreamEvent or ``None`` if the line is not a valid event.
    """
    if not text:
        return None
    if text.startswith(_SSE_DATA_PREFIX):
        text = text[len(_SSE_DATA_PREFIX) :]
    try:
        event_dict = json.loads(text)
    except json.JSONDecodeError:
        logger.debug("line=<%s> | skipping non-JSON line", text[:120])
        return None
    return StreamEvent.from_dict(event_dict)


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


_ERROR_MAP: dict[str, type[AgentCoreClientError]] = {
    "AccessDeniedException": AccessDeniedError,
    "ThrottlingException": ThrottledError,
}


def translate_error(exc: Any) -> AgentCoreClientError:
    """Translate a botocore ``ClientError`` into a typed exception.

    Extracts the error code from the response metadata and maps it to
    the appropriate :class:`AgentCoreClientError` subclass.  Unknown
    codes fall back to the base class.
    """
    code = exc.response.get("Error", {}).get("Code", "")
    message = exc.response.get("Error", {}).get("Message", str(exc))
    error_cls = _ERROR_MAP.get(code, AgentCoreClientError)
    return error_cls(f"[{code}] {message}" if code else message)


# ---------------------------------------------------------------------------
# Invocation body assembly
# ---------------------------------------------------------------------------


def build_invocation_body(
    *,
    prompt: str | None = None,
    content: list[dict[str, Any]] | None = None,
    messages: list[dict[str, Any]] | None = None,
    payload_extras: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build the JSON body for an ``/invocations`` request.

    Validates that exactly one of ``prompt`` / ``content`` / ``messages``
    is supplied and merges ``payload_extras`` for forward-compatibility.

    Args:
        prompt: Plain string user turn.
        content: A list of Strands ``ContentBlock`` dicts.
        messages: A full ``Messages`` list.
        payload_extras: Additional keys merged into the body.

    Returns:
        A dict ready for ``json.dumps``.

    Raises:
        ValueError: When zero or multiple primary keys are supplied.
    """
    provided = [
        name
        for name, value in (("prompt", prompt), ("content", content), ("messages", messages))
        if value is not None
    ]
    if not provided:
        raise ValueError("exactly one of prompt=, content=, messages= is required")
    if len(provided) > 1:
        raise ValueError(
            "exactly one of prompt=, content=, messages= is required, got %s" % ", ".join(provided)
        )

    body: dict[str, Any] = {}
    if payload_extras:
        body.update(payload_extras)
    if prompt is not None:
        body["prompt"] = prompt
    elif content is not None:
        body["content"] = content
    else:
        body["messages"] = messages
    return body
