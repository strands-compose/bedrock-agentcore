"""Tests for the shared REPL loop (client/repl.py).

Drives run_repl with a recording stream_fn and a scripted input() so no real
terminal is needed.  Asserts observable outcomes: whether the prompt reached
stream_fn, and that control commands / interrupts exit or short-circuit.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

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


class _Recorder:
    """A stream_fn that records the prompts it was asked to stream."""

    def __init__(self, *, returns: bool = True) -> None:
        self.returns = returns
        self.prompts: list[str] = []
        self.sessions: list[str] = []

    def __call__(self, msg: str, sid: str, renderer) -> bool:
        self.prompts.append(msg)
        self.sessions.append(sid)
        return self.returns


class TestReplExitWithoutStreaming:
    """Inputs that end the loop or are handled locally never reach stream_fn."""

    @pytest.mark.parametrize("first_input", ["", "/exit", "/quit", "/session", "/help", "/clear"])
    def test_control_input_does_not_stream(self, first_input: str) -> None:
        recorder = _Recorder()
        # A trailing "" guarantees the loop terminates after a slash command.
        with patch("builtins.input", _make_input_fn([first_input, ""])):
            run_repl(banner="Test", session_id="sid", stream_fn=recorder)

        assert recorder.prompts == []

    def test_eof_error_exits_without_streaming(self) -> None:
        recorder = _Recorder()
        with patch("builtins.input", side_effect=EOFError):
            run_repl(banner="Test", session_id="sid", stream_fn=recorder)

        assert recorder.prompts == []

    def test_keyboard_interrupt_exits_gracefully(self) -> None:
        recorder = _Recorder()
        with patch("builtins.input", side_effect=KeyboardInterrupt):
            run_repl(banner="Test", session_id="sid", stream_fn=recorder)

        assert recorder.prompts == []


class TestReplStreaming:
    """Normal prompts are forwarded to stream_fn with the session id."""

    def test_prompt_and_session_id_forwarded_to_stream_fn(self) -> None:
        recorder = _Recorder()
        with patch("builtins.input", _make_input_fn(["Hello world", ""])):
            run_repl(banner="Test", session_id="my-session", stream_fn=recorder)

        assert recorder.prompts == ["Hello world"]
        assert recorder.sessions == ["my-session"]

    def test_multiple_prompts_stream_in_order(self) -> None:
        recorder = _Recorder()
        with patch("builtins.input", _make_input_fn(["first", "second", ""])):
            run_repl(banner="Test", session_id="sid", stream_fn=recorder)

        assert recorder.prompts == ["first", "second"]

    def test_unknown_slash_command_is_sent_as_prompt(self) -> None:
        recorder = _Recorder()
        with patch("builtins.input", _make_input_fn(["/unknown", ""])):
            run_repl(banner="Test", session_id="sid", stream_fn=recorder)

        assert recorder.prompts == ["/unknown"]

    def test_loop_exits_when_stream_fn_returns_false(self) -> None:
        recorder = _Recorder(returns=False)
        with patch("builtins.input", _make_input_fn(["msg1", "msg2", "msg3"])):
            run_repl(banner="Test", session_id="sid", stream_fn=recorder)

        assert recorder.prompts == ["msg1"]
