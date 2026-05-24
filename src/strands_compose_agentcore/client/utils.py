"""Shared client helpers: SSE parsing, error translation, body assembly."""

from __future__ import annotations

import json
import logging
from typing import Any

from strands_compose import StreamEvent

from ..types import (
    AccessDeniedError,
    AgentCoreClientError,
    AgentInput,
    ConflictError,
    InvalidRequestError,
    RetryableConflictError,
    SessionNotFoundError,
    ThrottledError,
)

logger = logging.getLogger(__name__)


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
# Error translation
# ---------------------------------------------------------------------------


_ERROR_MAP: dict[str, type[AgentCoreClientError]] = {
    "AccessDeniedException": AccessDeniedError,
    "ThrottlingException": ThrottledError,
    "ResourceNotFoundException": SessionNotFoundError,
    "ValidationException": InvalidRequestError,
    "ConflictException": ConflictError,
    "RetryableConflictException": RetryableConflictError,
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


def build_invocation_body(agent_input: AgentInput) -> dict[str, Any]:
    """Build the JSON body for an ``/invocations`` request.

    The wire carries a single ``prompt`` key whose value mirrors the
    ``AgentInput`` shape:

    * ``str`` -> ``{"prompt": str}``
    * one content-block dict -> ``{"prompt": [dict]}``
    * non-empty list of content blocks -> ``{"prompt": [...]}``

    Args:
        agent_input: Prompt text, a single content block, or a list of
            content blocks.

    Returns:
        A dict ready for ``json.dumps``.

    Raises:
        ValueError: ``agent_input`` is not a supported shape.
    """
    if isinstance(agent_input, str):
        return {"prompt": agent_input}
    if isinstance(agent_input, dict):
        return {"prompt": [agent_input]}
    if isinstance(agent_input, list) and agent_input:
        return {"prompt": list(agent_input)}
    raise ValueError("invalid agent_input: %r" % (agent_input,))
