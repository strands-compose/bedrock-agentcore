"""Tests for CLI commands: cmd_dev, cmd_client, main()."""

from __future__ import annotations

import argparse
from unittest.mock import MagicMock, patch

import pytest

from strands_compose_agentcore.cli import main
from strands_compose_agentcore.cli.client import cmd_client
from strands_compose_agentcore.cli.dev import cmd_dev
from strands_compose_agentcore.cli.utils import CLIError


class TestCmdDev:
    """cmd_dev raises CLIError for missing config file."""

    def test_cmd_dev_raises_cli_error_for_missing_config(self) -> None:
        args = argparse.Namespace(config="nonexistent.yaml", port=8080, session_id=None)
        with pytest.raises(CLIError, match="not found"):
            cmd_dev(args)

    def test_cmd_dev_raises_cli_error_for_missing_comma_separated_config(self) -> None:
        args = argparse.Namespace(config="a.yaml,b.yaml", port=8080, session_id=None)
        with pytest.raises(CLIError, match="not found"):
            cmd_dev(args)


class TestCmdClient:
    """cmd_client dispatches to correct client REPL."""

    def test_cmd_client_local_dispatches_to_local_client_repl(self) -> None:
        args = argparse.Namespace(
            client_command="local",
            url="http://localhost:8080/invocations",
            session_id=None,
        )
        with patch("strands_compose_agentcore.cli.client.LocalClient") as mock_cls:
            mock_instance = MagicMock()
            mock_cls.return_value = mock_instance
            cmd_client(args, MagicMock())
            mock_instance.repl.assert_called_once()

    def test_cmd_client_remote_dispatches_to_agentcore_client_repl(self) -> None:
        args = argparse.Namespace(
            client_command="remote",
            arn="arn:aws:bedrock:us-east-1:123:agent-runtime/test",
            region="us-east-1",
            session_id="s" * 33,
        )
        with patch("strands_compose_agentcore.cli.client.AgentCoreClient") as mock_cls:
            mock_instance = MagicMock()
            mock_cls.return_value = mock_instance
            cmd_client(args, MagicMock())
            mock_instance.repl.assert_called_once()


class TestMainEntrypoint:
    """main() catches CLIError and calls sys.exit."""

    def test_main_exits_with_cli_error_code(self) -> None:
        with patch("strands_compose_agentcore.cli.cmd_dev", side_effect=CLIError("oops", code=2)):
            with pytest.raises(SystemExit) as exc_info:
                main(["dev"])
            assert exc_info.value.code == 2

    def test_main_exits_1_for_unknown_command(self) -> None:
        with pytest.raises(SystemExit) as exc_info:
            main([])
        assert exc_info.value.code == 1
