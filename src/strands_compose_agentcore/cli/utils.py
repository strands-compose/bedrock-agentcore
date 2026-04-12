"""Shared CLI utilities: ANSI colour helpers and exception types."""

from __future__ import annotations

import sys

from .._utils import ansi  # noqa: F401 — re-exported for cli consumers

# ---------------------------------------------------------------------------
# Colours — call-time TTY detection via ansi()
# ---------------------------------------------------------------------------


def red() -> str:
    """Return ANSI red escape for stderr."""
    return ansi("31", sys.stderr)


def reset() -> str:
    """Return ANSI reset escape for stderr."""
    return ansi("0", sys.stderr)


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------


class CLIError(Exception):
    """Raised by CLI commands to signal a user-facing error.

    ``main()`` catches this, prints the message to stderr, and calls
    ``sys.exit(code)`` — keeping command handlers testable without
    catching ``SystemExit``.

    Args:
        message: Human-readable error message.
        code: Exit code (default ``1``).
    """

    def __init__(self, message: str, code: int = 1) -> None:
        super().__init__(message)
        self.message = message
        self.code = code
