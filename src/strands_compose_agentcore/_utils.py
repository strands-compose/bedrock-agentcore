"""Internal shared utilities — ANSI helpers, TTY detection, session ID validation.

This module is private (underscore prefix) and should not be imported
by external code.
"""

from __future__ import annotations

import sys
from typing import Any, TextIO

from strands_compose import StreamEvent

# AgentCore session ID length constraints.
_MIN_SESSION_ID_LENGTH = 33
_MAX_SESSION_ID_LENGTH = 256


def ansi(code: str, stream: TextIO = sys.stderr) -> str:
    """Return an ANSI escape sequence if *stream* is a TTY, else empty string.

    Args:
        code: ANSI escape code (e.g. ``"31"`` for red).
        stream: Stream to check for TTY support.
    """
    return f"\033[{code}m" if stream.isatty() else ""


def validate_session_id(session_id: str | None) -> None:
    """Validate AgentCore session ID length (33-256 chars).

    Args:
        session_id: Session ID to check.  ``None`` is accepted (the
            runtime header may be absent in dev/test contexts).

    Raises:
        ValueError: ``session_id`` is outside the 33-256 char range.
    """
    if session_id is None:
        return
    length = len(session_id)
    if length < _MIN_SESSION_ID_LENGTH:
        raise ValueError(
            f"session_id=<{session_id}> is too short ({length} chars). "
            f"AgentCore requires at least {_MIN_SESSION_ID_LENGTH} characters."
        )
    if length > _MAX_SESSION_ID_LENGTH:
        raise ValueError(
            f"session_id=<{session_id[:20]}...> is too long ({length} chars). "
            f"AgentCore allows at most {_MAX_SESSION_ID_LENGTH} characters."
        )


def error_event(
    message: str,
    *,
    exception_type: str = "AdapterError",
    **extra: Any,
) -> StreamEvent:
    """Build an error StreamEvent mirroring the upstream ``text``/``exception_type`` schema.

    Args:
        message: Human-readable error text, stored in ``data["text"]``.
        exception_type: Machine-readable discriminator (``type(exc).__name__``
            or a synthetic token like ``"AgentBusy"``).
        **extra: Additional key-value pairs merged into ``data``.

    Returns:
        A ``StreamEvent`` with ``type="error"`` and an empty ``agent_name``.
    """
    data: dict[str, Any] = {"text": message, "exception_type": exception_type}
    data.update(extra)
    return StreamEvent(
        type="error",
        agent_name="",
        data=data,
    )
