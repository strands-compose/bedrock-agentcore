"""Internal shared utilities — ANSI helpers, TTY detection, session ID validation.

This module is private (underscore prefix) and should not be imported
by external code.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, TextIO

from strands_compose import AppConfig, ResolvedInfra, StreamEvent, load_config, resolve_infra

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


def error_event(message: str, **extra: Any) -> StreamEvent:
    """Build an error StreamEvent.

    Args:
        message: Human-readable error text. Stored verbatim in
            ``data["message"]``.
        **extra: Additional key-value pairs merged into ``data``.

    Returns:
        A ``StreamEvent`` with ``type="error"`` and an empty
        ``agent_name``.  Call ``.asdict()`` to obtain the JSON-friendly
        form yielded from the ``/invocations`` entrypoint.
    """
    data: dict[str, Any] = {"text": message}
    data.update(extra)
    return StreamEvent(
        type="error",
        agent_name="",
        data=data,
    )


def prepare_app_state(
    config: str | Path | list[str | Path] | AppConfig,
    infra: ResolvedInfra | None,
) -> tuple[AppConfig, ResolvedInfra]:
    """Resolve the polymorphic config argument into AppConfig + infra.

    - If ``config`` is ``str``, ``Path``, or ``list``, calls
      ``load_config(config)``; otherwise uses ``config`` directly.
    - Validates that ``app_config.entry`` is set, raising ``ValueError``
      with the exact existing message.
    - If ``infra`` is ``None``, calls ``resolve_infra(app_config)`` and
      returns the result; otherwise returns ``infra`` unchanged.

    Args:
        config: YAML file path, raw YAML string, list of either, or a
            pre-built ``AppConfig``.
        infra: Optional pre-resolved infrastructure.

    Returns:
        ``(AppConfig, ResolvedInfra)``.

    Raises:
        ValueError: ``app_config.entry`` is ``None`` or empty.
    """
    if isinstance(config, (str, Path, list)):
        app_config = load_config(config)
    else:
        app_config = config

    if not getattr(app_config, "entry", None):
        raise ValueError(
            "config has no 'entry' defined - set 'entry: <agent_name>' in your YAML config"
        )

    if infra is None:
        infra = resolve_infra(app_config)

    return app_config, infra
