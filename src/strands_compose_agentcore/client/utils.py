"""Shared client helpers: SSE parsing, error translation, body assembly, AWS streams."""

from __future__ import annotations

import json
import logging
from contextlib import suppress
from typing import TYPE_CHECKING, Any

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

if TYPE_CHECKING:
    from collections.abc import Iterator

    from urllib3 import HTTPResponse

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
    text = text.removeprefix(_SSE_DATA_PREFIX)
    try:
        event_dict = json.loads(text)
    except json.JSONDecodeError:
        logger.debug("len=<%d> | skipping non-JSON SSE line", len(text))
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


def build_invocation_body(agent_input: AgentInput, *, user_id: str | None = None) -> dict[str, Any]:
    """Build the JSON body for an ``/invocations`` request.

    The ``prompt`` key's value mirrors the ``AgentInput`` shape:

    * ``str`` -> ``{"prompt": str}``
    * one content-block dict -> ``{"prompt": [dict]}``
    * non-empty list of content blocks -> ``{"prompt": [...]}``

    A ``user_id`` key is added next to ``prompt`` when given.

    Args:
        agent_input: Prompt text, a single content block, or a list of
            content blocks.
        user_id: Optional caller-supplied user identifier.

    Returns:
        A dict ready for ``json.dumps``.

    Raises:
        ValueError: ``agent_input`` is not a supported shape.
    """
    body: dict[str, Any]
    if isinstance(agent_input, str):
        body = {"prompt": agent_input}
    elif isinstance(agent_input, dict):
        body = {"prompt": [agent_input]}
    elif isinstance(agent_input, list) and agent_input:
        body = {"prompt": list(agent_input)}
    else:
        raise ValueError(f"invalid agent_input: {agent_input!r}")
    if user_id is not None:
        body["user_id"] = user_id
    return body


# ---------------------------------------------------------------------------
# AgentCore response stream (the urllib3 response inside a StreamingBody)
# ---------------------------------------------------------------------------

# read1() returns what has already arrived, so this caps per-stream buffering
# without holding small events back.
_READ_SIZE = 64 * 1024


def iter_lines(response: HTTPResponse) -> Iterator[bytes]:
    """Yield each line of an AgentCore response as soon as its newline arrives.

    botocore's ``StreamingBody.iter_lines`` reads fixed-size chunks, so an
    event that does not fill one waits for the next event.  ``read1()``
    returns whatever has arrived.  urllib3 errors are re-raised as the
    botocore exceptions ``StreamingBody`` raises.

    Yields:
        Lines without their line ending; a blank line is ``b""``.
    """
    from botocore.exceptions import ReadTimeoutError, ResponseStreamingError
    from urllib3.exceptions import ProtocolError
    from urllib3.exceptions import ReadTimeoutError as Urllib3ReadTimeoutError

    pending = b""
    try:
        while chunk := response.read1(_READ_SIZE):
            lines = (pending + chunk).splitlines(keepends=True)
            pending = b"" if lines[-1].endswith((b"\n", b"\r")) else lines.pop()
            yield from (line.rstrip(b"\r\n") for line in lines)
    except Urllib3ReadTimeoutError as exc:
        raise ReadTimeoutError(endpoint_url=str(exc.url), error=exc) from exc
    except ProtocolError as exc:
        raise ResponseStreamingError(error=exc) from exc
    if pending:
        yield pending


def abort_stream(response: HTTPResponse) -> None:
    """Wake a thread blocked reading ``response``; its read then fails.

    ``close()`` alone would wait for that read to return, up to the socket
    read timeout.  After this, ``close()`` returns at once.
    """
    with suppress(ValueError, RuntimeError, OSError):  # already closed or fully read
        response.shutdown()
