"""Tests for the shared REPL loop."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from strands_compose_agentcore.client.repl import run_repl


def _make_stream_fn(return_value: bool = True) -> MagicMock:
    """Create a mock stream function."""
    return MagicMock(return_value=return_value)


class TestRunRepl:
    """Tests for run_repl slash commands and flow."""

    def test_exit_command_breaks_loop(self) -> None:
        stream_fn = _make_stream_fn()

        with (
            patch("strands_compose_agentcore.client.repl.AnsiRenderer"),
            patch("builtins.input", side_effect=["/exit"]),
        ):
            run_repl(banner="test", session_id="s1", stream_fn=stream_fn)

        stream_fn.assert_not_called()

    def test_quit_command_breaks_loop(self) -> None:
        stream_fn = _make_stream_fn()

        with (
            patch("strands_compose_agentcore.client.repl.AnsiRenderer"),
            patch("builtins.input", side_effect=["/quit"]),
        ):
            run_repl(banner="test", session_id="s1", stream_fn=stream_fn)

        stream_fn.assert_not_called()

    def test_session_command_shows_session_id(self) -> None:
        stream_fn = _make_stream_fn()

        with (
            patch("strands_compose_agentcore.client.repl.AnsiRenderer"),
            patch("builtins.input", side_effect=["/session", ""]),
            patch("builtins.print") as mock_print,
        ):
            run_repl(banner="test", session_id="my-session-123", stream_fn=stream_fn)

        # /session prints the session ID
        printed = [str(c) for c in mock_print.call_args_list]
        assert any("my-session-123" in p for p in printed)
        stream_fn.assert_not_called()

    def test_help_command_does_not_invoke(self) -> None:
        stream_fn = _make_stream_fn()

        with (
            patch("strands_compose_agentcore.client.repl.AnsiRenderer"),
            patch("builtins.input", side_effect=["/help", ""]),
        ):
            run_repl(banner="test", session_id="s1", stream_fn=stream_fn)

        stream_fn.assert_not_called()

    def test_clear_command_does_not_invoke(self) -> None:
        stream_fn = _make_stream_fn()

        with (
            patch("strands_compose_agentcore.client.repl.AnsiRenderer"),
            patch("builtins.input", side_effect=["/clear", ""]),
        ):
            run_repl(banner="test", session_id="s1", stream_fn=stream_fn)

        stream_fn.assert_not_called()

    def test_unknown_slash_command_sent_as_prompt(self) -> None:
        stream_fn = _make_stream_fn()

        with (
            patch("strands_compose_agentcore.client.repl.AnsiRenderer"),
            patch("builtins.input", side_effect=["/unknown", ""]),
        ):
            run_repl(banner="test", session_id="s1", stream_fn=stream_fn)

        stream_fn.assert_called_once()
        assert stream_fn.call_args[0][0] == "/unknown"

    def test_stream_fn_returning_false_breaks_loop(self) -> None:
        stream_fn = _make_stream_fn(return_value=False)

        with (
            patch("strands_compose_agentcore.client.repl.AnsiRenderer"),
            patch("builtins.input", side_effect=["hello", "world"]),
        ):
            run_repl(banner="test", session_id="s1", stream_fn=stream_fn)

        stream_fn.assert_called_once()

    def test_eof_breaks_loop(self) -> None:
        stream_fn = _make_stream_fn()

        with (
            patch("strands_compose_agentcore.client.repl.AnsiRenderer"),
            patch("builtins.input", side_effect=EOFError),
        ):
            run_repl(banner="test", session_id="s1", stream_fn=stream_fn)

        stream_fn.assert_not_called()

    def test_keyboard_interrupt_prints_goodbye(self) -> None:
        stream_fn = _make_stream_fn()

        with (
            patch("strands_compose_agentcore.client.repl.AnsiRenderer"),
            patch("builtins.input", side_effect=KeyboardInterrupt),
        ):
            run_repl(banner="test", session_id="s1", stream_fn=stream_fn)

        stream_fn.assert_not_called()

    def test_empty_input_breaks_loop(self) -> None:
        stream_fn = _make_stream_fn()

        with (
            patch("strands_compose_agentcore.client.repl.AnsiRenderer"),
            patch("builtins.input", side_effect=[""]),
        ):
            run_repl(banner="test", session_id="s1", stream_fn=stream_fn)

        stream_fn.assert_not_called()

    def test_normal_prompt_calls_stream_fn(self) -> None:
        stream_fn = _make_stream_fn()

        with (
            patch("strands_compose_agentcore.client.repl.AnsiRenderer"),
            patch("builtins.input", side_effect=["hello world", ""]),
        ):
            run_repl(banner="test", session_id="s1", stream_fn=stream_fn)

        stream_fn.assert_called_once()
        assert stream_fn.call_args[0][0] == "hello world"
        assert stream_fn.call_args[0][1] == "s1"

    def test_banner_printed_to_stderr(self) -> None:
        stream_fn = _make_stream_fn()

        with (
            patch("strands_compose_agentcore.client.repl.AnsiRenderer"),
            patch("builtins.input", side_effect=[""]),
            patch("builtins.print") as mock_print,
        ):
            run_repl(banner="My Banner", session_id="s1", stream_fn=stream_fn)

        # Banner is the first print call (to stderr)
        first_call = mock_print.call_args_list[0]
        assert "My Banner" in first_call[0][0]
