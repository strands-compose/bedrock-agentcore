"""CLI entry point for strands-compose-agentcore.

Provides:
- ``dev`` — server + REPL in one terminal
- ``client local|remote`` — REPL for local or deployed agents
"""

from __future__ import annotations

import argparse
import sys
from typing import NoReturn

from .client import cmd_client
from .dev import cmd_dev
from .utils import CLIError, red, reset


class _ColorArgumentParser(argparse.ArgumentParser):
    """ArgumentParser that prints errors in red with surrounding newlines."""

    def error(self, message: str) -> NoReturn:
        """Print a red error message and exit.

        Args:
            message: Error description from argparse.
        """
        print(
            f"\n{red()}{self.prog}: error:\n {message}{reset()}\n",
            file=sys.stderr,
        )
        sys.exit(2)


def _build_parser() -> argparse.ArgumentParser:
    """Build the argument parser with all subcommands.

    Returns:
        Configured ArgumentParser.
    """
    parser = _ColorArgumentParser(
        prog="sca",
        description="CLI toolkit for strands-compose agents on AgentCore.",
    )
    subparsers = parser.add_subparsers(dest="command")

    # -- dev (own implementation) ------------------------------------------
    dev_parser = subparsers.add_parser(
        "dev",
        help="Start server + REPL in one terminal.",
    )
    dev_parser.add_argument(
        "--config",
        default=None,
        help="Path to strands-compose YAML config (default: ./config.yaml).",
    )
    dev_parser.add_argument(
        "--port",
        type=int,
        default=8080,
        help="Port for the HTTP server (default: 8080).",
    )
    dev_parser.add_argument(
        "--session-id",
        default=None,
        help="Session ID for the REPL client",
    )

    # -- client (own implementation) ---------------------------------------
    client_parser = subparsers.add_parser(
        "client",
        help="Interactive REPL client for local or remote agents.",
    )
    client_sub = client_parser.add_subparsers(dest="client_command")

    local_parser = client_sub.add_parser(
        "local",
        help="Connect to a local server.",
    )
    local_parser.add_argument(
        "--url",
        default="http://localhost:8080/invocations",
        help="URL of the /invocations endpoint.",
    )
    local_parser.add_argument(
        "--session-id",
        default=None,
        help="Session ID for the AgentCore header.",
    )
    remote_parser = client_sub.add_parser(
        "remote",
        help="Connect to a deployed AgentCore Runtime agent.",
    )
    remote_parser.add_argument(
        "--arn",
        required=True,
        help="Full ARN of the deployed agent runtime.",
    )
    remote_parser.add_argument(
        "--region",
        default=None,
        help="AWS region override.",
    )
    remote_parser.add_argument(
        "--session-id",
        default=None,
        help="AgentCore session ID.",
    )

    return parser


def main(argv: list[str] | None = None) -> None:
    """Parse arguments and dispatch to the appropriate handler.

    Args:
        argv: Command-line arguments.  Defaults to ``sys.argv[1:]``.
    """
    if argv is None:
        argv = sys.argv[1:]

    parser = _build_parser()
    args = parser.parse_args(argv)

    try:
        if args.command == "dev":
            cmd_dev(args)

        elif args.command == "client":
            cmd_client(args, parser)

        else:
            parser.print_help()
            sys.exit(1)
    except CLIError as exc:
        print(f"\n{red()}{exc.message}{reset()}\n", file=sys.stderr)
        sys.exit(exc.code)


if __name__ == "__main__":
    main()
