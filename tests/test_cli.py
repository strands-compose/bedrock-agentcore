"""Tests for CLI parser and command dispatch behavior."""

from __future__ import annotations

import argparse
import socket
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from strands_compose_agentcore.cli import _build_parser, main
from strands_compose_agentcore.cli.dev import _port_in_use, _wait_for_server, cmd_dev, run_dev
from strands_compose_agentcore.cli.utils import CLIError

# ---------------------------------------------------------------------------
# Parser tests
# ---------------------------------------------------------------------------


class TestBuildParser:
    def test_dev_defaults(self) -> None:
        parser = _build_parser()
        args, _ = parser.parse_known_args(["dev"])
        assert args.command == "dev"
        assert args.config is None
        assert args.port == 8080
        assert args.session_id is None

    def test_dev_custom(self) -> None:
        parser = _build_parser()
        args, _ = parser.parse_known_args(
            ["dev", "--config", "my.yaml", "--port", "9090", "--session-id", "s1"]
        )
        assert args.config == "my.yaml"
        assert args.port == 9090
        assert args.session_id == "s1"

    def test_client_local_defaults(self) -> None:
        parser = _build_parser()
        args, _ = parser.parse_known_args(["client", "local"])
        assert args.command == "client"
        assert args.client_command == "local"
        assert args.url == "http://localhost:8080/invocations"
        assert args.session_id is None

    def test_client_local_custom(self) -> None:
        parser = _build_parser()
        args, _ = parser.parse_known_args(
            [
                "client",
                "local",
                "--url",
                "http://myhost:9000/invocations",
                "--session-id",
                "my-sess",
            ]
        )
        assert args.url == "http://myhost:9000/invocations"
        assert args.session_id == "my-sess"

    def test_client_remote_requires_arn(self) -> None:
        parser = _build_parser()
        with pytest.raises(SystemExit):
            parser.parse_known_args(["client", "remote"])

    def test_client_remote_defaults(self) -> None:
        parser = _build_parser()
        args, _ = parser.parse_known_args(["client", "remote", "--arn", "arn:aws:test"])
        assert args.command == "client"
        assert args.client_command == "remote"
        assert args.arn == "arn:aws:test"
        assert args.region is None
        assert args.session_id is None

    def test_client_remote_custom(self) -> None:
        parser = _build_parser()
        args, _ = parser.parse_known_args(
            [
                "client",
                "remote",
                "--arn",
                "arn:aws:test",
                "--region",
                "eu-west-1",
                "--session-id",
                "sess-123",
            ]
        )
        assert args.region == "eu-west-1"
        assert args.session_id == "sess-123"


# ---------------------------------------------------------------------------
# Dispatch — client
# ---------------------------------------------------------------------------


class TestMainClientLocal:
    @patch("strands_compose_agentcore.cli.client.LocalClient", autospec=False)
    def test_client_local_creates_client_and_calls_repl(self, mock_cls: MagicMock) -> None:
        mock_instance = MagicMock()
        mock_cls.return_value = mock_instance

        main(["client", "local", "--url", "http://x:1234/invocations", "--session-id", "s1"])

        mock_cls.assert_called_once_with(url="http://x:1234/invocations", session_id="s1")
        mock_instance.repl.assert_called_once()


class TestMainClientRemote:
    @patch("strands_compose_agentcore.cli.client.AgentCoreClient", autospec=False)
    def test_client_remote_creates_client_and_calls_repl(self, mock_cls: MagicMock) -> None:
        mock_instance = MagicMock()
        mock_cls.return_value = mock_instance

        main(
            [
                "client",
                "remote",
                "--arn",
                "arn:aws:test",
                "--region",
                "us-east-1",
                "--session-id",
                "s2",
            ]
        )

        mock_cls.assert_called_once_with("arn:aws:test", region="us-east-1")
        mock_instance.repl.assert_called_once_with(session_id="s2")


# ---------------------------------------------------------------------------
# Dispatch — no command
# ---------------------------------------------------------------------------


class TestMainNoCommand:
    def test_no_command_exits(self) -> None:
        with pytest.raises(SystemExit) as exc_info:
            main([])
        assert exc_info.value.code == 1


# ---------------------------------------------------------------------------
# _colors — module-level constants import
# ---------------------------------------------------------------------------


class TestColors:
    def test_ansi_function_imports_without_error(self) -> None:
        from strands_compose_agentcore._utils import ansi  # noqa: F401
        from strands_compose_agentcore.cli.utils import red, reset  # noqa: F401

    def test_red_and_reset_return_strings(self) -> None:
        from strands_compose_agentcore.cli.utils import red, reset

        assert isinstance(red(), str)
        assert isinstance(reset(), str)

    def test_ansi_returns_string(self) -> None:
        from strands_compose_agentcore._utils import ansi

        assert isinstance(ansi("31"), str)


# ---------------------------------------------------------------------------
# CLIError
# ---------------------------------------------------------------------------


class TestCLIError:
    def test_stores_message_and_default_code(self) -> None:
        err = CLIError("something went wrong")
        assert err.message == "something went wrong"
        assert err.code == 1

    def test_custom_code(self) -> None:
        err = CLIError("bad input", code=42)
        assert err.message == "bad input"
        assert err.code == 42

    def test_is_exception_subclass(self) -> None:
        assert issubclass(CLIError, Exception)
        assert not issubclass(CLIError, SystemExit)

    def test_caught_by_exception_handler(self) -> None:
        with pytest.raises(CLIError) as exc_info:
            raise CLIError("fail", code=3)
        assert exc_info.value.code == 3


# ---------------------------------------------------------------------------
# dev — cmd_dev
# ---------------------------------------------------------------------------


class TestCmdDev:
    def test_raises_cli_error_when_config_not_found(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.chdir(tmp_path)
        args = argparse.Namespace(config=None, port=8080, session_id="dev-session")

        with pytest.raises(CLIError) as exc_info:
            cmd_dev(args)
        assert "config not found" in exc_info.value.message

    def test_raises_cli_error_for_explicit_missing_config(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.chdir(tmp_path)
        args = argparse.Namespace(config="missing.yaml", port=8080, session_id="dev-session")

        with pytest.raises(CLIError) as exc_info:
            cmd_dev(args)
        assert "config not found: missing.yaml" in exc_info.value.message


# ---------------------------------------------------------------------------
# dev — _port_in_use
# ---------------------------------------------------------------------------


class TestPortInUse:
    def test_returns_false_for_unbound_port(self) -> None:
        # Use a high ephemeral port unlikely to be in use
        assert _port_in_use(59999) is False

    def test_returns_true_for_bound_port(self) -> None:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.bind(("127.0.0.1", 0))
            sock.listen(1)
            port = sock.getsockname()[1]

            assert _port_in_use(port) is True


# ---------------------------------------------------------------------------
# dev — _wait_for_server
# ---------------------------------------------------------------------------


class TestWaitForServer:
    def test_returns_false_on_timeout(self) -> None:
        result = _wait_for_server("http://127.0.0.1:59998/ping", timeout=0.1)
        assert result is False

    @patch("strands_compose_agentcore.cli.dev.urllib.request.urlopen")
    def test_returns_true_when_server_responds(self, mock_urlopen: MagicMock) -> None:
        mock_urlopen.return_value.__enter__ = MagicMock()
        mock_urlopen.return_value.__exit__ = MagicMock(return_value=False)

        result = _wait_for_server("http://localhost:9999/ping", timeout=5.0)
        assert result is True
        mock_urlopen.assert_called()


# ---------------------------------------------------------------------------
# dev — run_dev
# ---------------------------------------------------------------------------


class TestRunDev:
    @patch("strands_compose_agentcore.cli.dev._port_in_use", return_value=True)
    @patch("strands_compose_agentcore.cli.dev.create_app")
    def test_raises_cli_error_when_port_in_use(
        self, mock_create_app: MagicMock, mock_port: MagicMock
    ) -> None:
        with pytest.raises(CLIError) as exc_info:
            run_dev("config.yaml", session_id="test-session", port=8080)
        assert "port 8080 is already in use" in exc_info.value.message


# ---------------------------------------------------------------------------
# main — CLIError handling
# ---------------------------------------------------------------------------


class TestMainCLIErrorHandling:
    @patch("strands_compose_agentcore.cli.cmd_dev")
    def test_cli_error_prints_message_to_stderr_and_exits(
        self, mock_cmd_dev: MagicMock, capsys: pytest.CaptureFixture[str]
    ) -> None:
        mock_cmd_dev.side_effect = CLIError("boom", code=7)

        with pytest.raises(SystemExit) as exc_info:
            main(["dev"])

        assert exc_info.value.code == 7
        captured = capsys.readouterr()
        assert "boom" in captured.err
