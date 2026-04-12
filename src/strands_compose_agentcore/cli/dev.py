"""Dev command — server + REPL in one terminal."""

from __future__ import annotations

import argparse
import logging
import socket
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

from .. import create_app
from ..client.local import LocalClient
from .utils import CLIError

logger = logging.getLogger(__name__)

_SERVER_STARTUP_TIMEOUT = 30.0
_SERVER_POLL_INTERVAL = 0.5


def cmd_dev(args: argparse.Namespace) -> None:
    """Handle the ``dev`` subcommand.

    Args:
        args: Parsed CLI arguments (config, port, session_id).

    Raises:
        CLIError: Config file not found.
    """
    config_path = args.config or "config.yaml"
    if not Path(config_path).is_file():
        raise CLIError(f"Error: config not found: {config_path}")

    run_dev(config_path, port=args.port, session_id=args.session_id)


def run_dev(
    config: str | Path,
    *,
    session_id: str | None = None,
    port: int = 8080,
) -> None:
    """Start ASGI server in a daemon thread and run the REPL in main thread.

    Uses ``app.run()`` which internally calls ``uvicorn.run(self, ...)``
    with sensible defaults (host auto-detection, log levels, etc.).
    The daemon thread auto-terminates when the process exits.

    Args:
        config: Path to strands-compose YAML config file.
        port: Port for the HTTP server.
        session_id: Session ID for the REPL client.  When ``None``
            (the default), ``LocalClient`` uses ``DEFAULT_SESSION_ID``.

    Raises:
        CLIError: Port already in use or server startup timeout.
    """
    app = create_app(
        config,
        cors_origins=["*"],
        suppress_runtime_logging=True,
    )

    if _port_in_use(port):
        raise CLIError(
            f"Error: port {port} is already in use.\n"
            " Stop the other process or use --port <number>."
        )

    # Start the server in a daemon thread so it doesn't block the REPL
    server_thread = threading.Thread(
        target=app.run,
        kwargs={"port": port},
        daemon=True,
        name="dev-server",
    )
    server_thread.start()

    ping_url = f"http://localhost:{port}/ping"
    if not _wait_for_server(ping_url, timeout=_SERVER_STARTUP_TIMEOUT):
        raise CLIError(f"Error: server did not start within {_SERVER_STARTUP_TIMEOUT} seconds")

    url = f"http://localhost:{port}/invocations"
    client = LocalClient(url=url, session_id=session_id)
    client.repl()


def _wait_for_server(ping_url: str, timeout: float) -> bool:
    """Poll the /ping endpoint until the server responds or timeout expires.

    Args:
        ping_url: URL of the server's health-check endpoint.
        timeout: Maximum seconds to wait.

    Returns:
        True if server responded, False on timeout.
    """
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            # This urlopen call is safe - we just ping our local server
            # Security alert is false positive
            with urllib.request.urlopen(ping_url, timeout=2):  # nosec: B310
                return True
        except (OSError, urllib.error.URLError):
            time.sleep(_SERVER_POLL_INTERVAL)
    return False


def _port_in_use(port: int, host: str = "127.0.0.1") -> bool:
    """Check whether a TCP port is already bound.

    Args:
        port: Port number to check.
        host: Address to probe.

    Returns:
        True if the port is in use.
    """
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(1)
        return sock.connect_ex((host, port)) == 0
