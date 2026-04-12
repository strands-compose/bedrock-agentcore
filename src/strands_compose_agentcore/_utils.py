"""Internal shared utilities — ANSI helpers and TTY detection.

This module provides terminal colour helpers used by both the CLI and
client subpackages.  It is private (underscore prefix) and should not
be imported by external code.
"""

from __future__ import annotations

import sys
from typing import TextIO


def _stream_is_tty(stream: TextIO) -> bool:
    """Check whether a stream is connected to a terminal.

    Args:
        stream: File-like object to check.

    Returns:
        True if the stream is a TTY.
    """
    return hasattr(stream, "isatty") and stream.isatty()


def ansi(code: str, stream: TextIO = sys.stderr) -> str:
    """Return an ANSI escape sequence if *stream* is a TTY, else empty string.

    Evaluates TTY status at call time — safe to use in tests where
    streams may be redirected after import.

    Args:
        code: ANSI escape code (e.g. ``"31"`` for red).
        stream: Stream to check for TTY support.

    Returns:
        The escape sequence or an empty string.
    """
    return f"\033[{code}m" if _stream_is_tty(stream) else ""
