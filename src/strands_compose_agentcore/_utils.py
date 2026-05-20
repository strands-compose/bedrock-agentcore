"""Internal shared utilities — ANSI helpers, TTY detection, session ID validation.

This module is private (underscore prefix) and should not be imported
by external code.
"""

from __future__ import annotations

import sys
from typing import TextIO

# AgentCore session ID length constraints.
_MIN_SESSION_ID_LENGTH = 33
_MAX_SESSION_ID_LENGTH = 256


def _stream_is_tty(stream: TextIO) -> bool:
    """Return True if *stream* is a TTY."""
    return hasattr(stream, "isatty") and stream.isatty()


def ansi(code: str, stream: TextIO = sys.stderr) -> str:
    """Return an ANSI escape sequence if *stream* is a TTY, else empty string.

    Args:
        code: ANSI escape code (e.g. ``"31"`` for red).
        stream: Stream to check for TTY support.
    """
    return f"\033[{code}m" if _stream_is_tty(stream) else ""


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
            "session_id=<%s> is too short (%d chars). "
            "AgentCore requires at least %d characters."
            % (session_id, length, _MIN_SESSION_ID_LENGTH)
        )
    if length > _MAX_SESSION_ID_LENGTH:
        raise ValueError(
            "session_id=<%s...> is too long (%d chars). "
            "AgentCore allows at most %d characters."
            % (session_id[:20], length, _MAX_SESSION_ID_LENGTH)
        )
