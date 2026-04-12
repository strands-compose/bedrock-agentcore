"""Shared REPL loop for interactive client sessions."""

from __future__ import annotations

import sys
from collections.abc import Callable

from strands_compose import AnsiRenderer

from .._utils import ansi

__all__ = ["run_repl"]


def run_repl(
    *,
    banner: str,
    session_id: str,
    stream_fn: Callable[[str, str, AnsiRenderer], bool],
) -> None:
    """Run an interactive REPL with slash commands and ANSI colours.

    The REPL prints a banner, reads user input with a light-green
    prompt, dispatches slash commands, and delegates streaming to
    *stream_fn*.

    Args:
        banner: Header line shown on startup (e.g. client type + URL).
        session_id: Session identifier displayed by ``/session``.
        stream_fn: Called as ``stream_fn(prompt, session_id, renderer)``.
            Must render events and call ``renderer.flush()``.
            Return ``True`` to continue the loop, ``False`` to break
            (e.g. on connection error).
    """
    renderer = AnsiRenderer(typewriter_delay=0.0025)

    _green = ansi("92", sys.stdout)
    _blue = ansi("94", sys.stdout)
    _reset = ansi("0", sys.stdout)
    _dim = ansi("2", sys.stdout)

    print(f"\n{banner}", file=sys.stderr)
    print("Type a message and press Enter. /help for commands.\n", file=sys.stderr)

    try:
        while True:
            try:
                msg = input(f"{_green}You: ").strip()
            except EOFError:
                break
            finally:
                sys.stdout.write(_reset)
                sys.stdout.flush()
            if not msg:
                break

            if msg.startswith("/"):
                cmd = msg.split(maxsplit=1)[0].lower()
                if cmd in ("/exit", "/quit"):
                    break
                if cmd == "/clear":
                    sys.stdout.write("\033[3J\033[2J\033[H")
                    sys.stdout.flush()
                    continue
                if cmd == "/session":
                    print(f"{_dim}session_id={session_id}{_reset}")
                    continue
                if cmd == "/help":
                    print(
                        "\n"
                        f"{_dim}/help       show this message\n"
                        f"/clear      clear the screen\n"
                        f"/session    show current session ID\n"
                        f"/exit       exit the REPL{_reset}\n"
                    )
                    continue
                # Unknown slash command — send as normal prompt

            ok = stream_fn(msg, session_id, renderer)
            if not ok:
                break
            print()
    except KeyboardInterrupt:
        print(f"\n\n{_blue}Goodbye!{_reset}\n", file=sys.stderr)
