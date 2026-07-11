"""Tests for the shared REPL loop (client/repl.py).

Uses a fake stream_fn and monkeypatched input() to drive run_repl
without a real terminal.  Tests verify observable outcomes: loop exit,
stream_fn invocation, slash command handling, and graceful interrupts.
"""

from __future__ import annotations

from unittest.mock import patch

from strands_compose_agentcore.client.repl import run_repl


def _make_input_fn(responses: list[str]):
    """Build an input() replacement that yields responses then raises EOFError."""
    it = iter(responses)

    def _fake_input(prompt: str = "") -> str:
        try:
            return next(it)
        except StopIteration:
            raise EOFError

    return _fake_input


class TestReplExitBehaviour:
    """run_repl exits on empty input, /exit, /quit, and EOFError."""

    def test_exits_on_empty_input(self) -> None:
        called = False

        def stream_fn(msg, sid, renderer):
            nonlocal called
            called = True
            return True

        with patch("builtins.input", _make_input_fn([""])):
            run_repl(banner="Test", session_id="test-sid", stream_fn=stream_fn)

        assert not called

    def test_exits_on_eof_error(self) -> None:
        called = False

        def stream_fn(msg, sid, renderer):
            nonlocal called
            called = True
            return True

        with patch("builtins.input", side_effect=EOFError):
            run_repl(banner="Test", session_id="test-sid", stream_fn=stream_fn)

        assert not called

    def test_exits_on_slash_exit(self) -> None:
        called = False

        def stream_fn(msg, sid, renderer):
            nonlocal called
            called = True
            return True

        with patch("builtins.input", _make_input_fn(["/exit"])):
            run_repl(banner="Test", session_id="test-sid", stream_fn=stream_fn)

        assert not called

    def test_exits_on_slash_quit(self) -> None:
        called = False

        def stream_fn(msg, sid, renderer):
            nonlocal called
            called = True
            return True

        with patch("builtins.input", _make_input_fn(["/quit"])):
            run_repl(banner="Test", session_id="test-sid", stream_fn=stream_fn)

        assert not called


class TestReplStreamFnInvocation:
    """run_repl calls stream_fn with correct arguments for normal prompts."""

    def test_stream_fn_called_with_prompt_and_session_id(self) -> None:
        captured_args: list[tuple] = []

        def stream_fn(msg, sid, renderer):
            captured_args.append((msg, sid))
            return True

        with patch("builtins.input", _make_input_fn(["Hello world", ""])):
            run_repl(banner="Test", session_id="my-session", stream_fn=stream_fn)

        assert len(captured_args) == 1
        assert captured_args[0][0] == "Hello world"
        assert captured_args[0][1] == "my-session"

    def test_stream_fn_called_multiple_times_for_multiple_prompts(self) -> None:
        captured_msgs: list[str] = []

        def stream_fn(msg, sid, renderer):
            captured_msgs.append(msg)
            return True

        with patch("builtins.input", _make_input_fn(["first", "second", ""])):
            run_repl(banner="Test", session_id="sid", stream_fn=stream_fn)

        assert captured_msgs == ["first", "second"]

    def test_exits_when_stream_fn_returns_false(self) -> None:
        call_count = 0

        def stream_fn(msg, sid, renderer):
            nonlocal call_count
            call_count += 1
            return False

        with patch("builtins.input", _make_input_fn(["msg1", "msg2", "msg3"])):
            run_repl(banner="Test", session_id="sid", stream_fn=stream_fn)

        # Should exit after first call returns False
        assert call_count == 1

    def test_unknown_slash_command_sent_as_normal_prompt(self) -> None:
        captured_msgs: list[str] = []

        def stream_fn(msg, sid, renderer):
            captured_msgs.append(msg)
            return True

        with patch("builtins.input", _make_input_fn(["/unknown", ""])):
            run_repl(banner="Test", session_id="sid", stream_fn=stream_fn)

        assert captured_msgs == ["/unknown"]


class TestReplSlashCommands:
    """Slash commands are handled without calling stream_fn."""

    def test_slash_session_does_not_call_stream_fn(self) -> None:
        called = False

        def stream_fn(msg, sid, renderer):
            nonlocal called
            called = True
            return True

        with patch("builtins.input", _make_input_fn(["/session", ""])):
            run_repl(banner="Test", session_id="my-sid", stream_fn=stream_fn)

        assert not called

    def test_slash_help_does_not_call_stream_fn(self) -> None:
        called = False

        def stream_fn(msg, sid, renderer):
            nonlocal called
            called = True
            return True

        with patch("builtins.input", _make_input_fn(["/help", ""])):
            run_repl(banner="Test", session_id="sid", stream_fn=stream_fn)

        assert not called

    def test_slash_clear_does_not_call_stream_fn(self) -> None:
        called = False

        def stream_fn(msg, sid, renderer):
            nonlocal called
            called = True
            return True

        with patch("builtins.input", _make_input_fn(["/clear", ""])):
            run_repl(banner="Test", session_id="sid", stream_fn=stream_fn)

        assert not called


class TestReplKeyboardInterrupt:
    """run_repl handles KeyboardInterrupt gracefully."""

    def test_keyboard_interrupt_exits_gracefully(self) -> None:
        def stream_fn(msg, sid, renderer):
            return True

        with patch("builtins.input", side_effect=KeyboardInterrupt):
            # Should not raise -- exits gracefully
            run_repl(banner="Test", session_id="sid", stream_fn=stream_fn)
