"""Client subcommands — local and remote REPL."""

from __future__ import annotations

import argparse

from ..client import AgentCoreClient, LocalClient


def cmd_client(args: argparse.Namespace, parser: argparse.ArgumentParser) -> None:
    """Handle the ``client`` subcommand.

    Args:
        args: Parsed CLI arguments.
        parser: Root parser (for --help fallback).
    """
    if args.client_command == "local":
        client = LocalClient(url=args.url, session_id=args.session_id)
        client.repl()

    elif args.client_command == "remote":
        client = AgentCoreClient(args.arn, region=args.region)
        client.repl(session_id=args.session_id)

    else:
        parser.parse_args(["client", "--help"])
