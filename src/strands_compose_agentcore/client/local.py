"""Sync HTTP client for invoking a local strands-compose-agentcore server.

Provides :class:`LocalClient` — a lightweight client that sends prompts
to a local ``/invocations`` endpoint and yields
:class:`~strands_compose.StreamEvent` objects parsed from the SSE
response.  No async, no boto3, no extra dependencies — just ``urllib``.

Events stream in real-time: each SSE line is yielded as soon as it
arrives from the socket, so callers see tokens appearing progressively.

Example::

    from strands_compose_agentcore import LocalClient

    for event in LocalClient().invoke(prompt="Hello"):
        print(event.type, event.data)

Interactive REPL::

    LocalClient().repl()
"""

from __future__ import annotations

import json
import sys
from typing import TYPE_CHECKING
from urllib.error import URLError
from urllib.request import Request, urlopen

from .utils import DEFAULT_SESSION_ID, ClientConnectionError, parse_sse_line

if TYPE_CHECKING:
    from collections.abc import Generator

    from strands_compose import AnsiRenderer, StreamEvent

__all__ = ["LocalClient"]


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_DEFAULT_URL = "http://localhost:8080/invocations"
_SESSION_HEADER = "X-Amzn-Bedrock-AgentCore-Runtime-Session-Id"


# ---------------------------------------------------------------------------
# Client
# ---------------------------------------------------------------------------


class LocalClient:
    def __init__(
        self,
        url: str = _DEFAULT_URL,
        *,
        session_id: str | None = None,
    ) -> None:
        """Sync HTTP client for a local strands-compose-agentcore server.

        Sends prompts to the ``/invocations`` endpoint and yields
        :class:`~strands_compose.StreamEvent` objects from the SSE
        response.  Pure synchronous — no asyncio, no boto3, no threads.

        Events are yielded as they arrive, giving real-time streaming
        output when paired with :class:`~strands_compose.AnsiRenderer`.

        Args:
            url: URL of the ``/invocations`` endpoint.  Defaults to
                ``http://localhost:8080/invocations``.
            session_id: Session ID for the AgentCore header.  When
                ``None`` (the default), uses
                ``DEFAULT_SESSION_ID``.

        Attributes:
            url: Full URL of the ``/invocations`` endpoint.
            session_id: Session ID sent in the AgentCore header.

        -------------------------------
        Example::

            client = LocalClient("http://localhost:8080/invocations")
            for event in client.invoke(prompt="Hello"):
                print(event.type, event.data)
        """
        self.url = url
        self.session_id = session_id or DEFAULT_SESSION_ID

    def invoke(
        self,
        *,
        prompt: str,
        session_id: str | None = None,
    ) -> Generator[StreamEvent, None, None]:
        """Send a prompt and yield streaming events.

        Opens an HTTP connection to the local server and reads SSE
        lines as they arrive.  Each valid JSON line is parsed into a
        :class:`~strands_compose.StreamEvent` and yielded.

        Args:
            prompt: User message to send.
            session_id: Override the default session ID for this call.

        Yields:
            StreamEvent objects parsed from the SSE response.

        Raises:
            ClientConnectionError: Could not connect to the server.
        """
        sid = session_id or self.session_id
        body = json.dumps({"prompt": prompt}).encode()
        req = Request(
            self.url,
            data=body,
            headers={
                "Content-Type": "application/json",
                _SESSION_HEADER: sid,
            },
            method="POST",
        )

        try:
            with urlopen(req) as resp:  # noqa: S310  # nosec B310 — local server
                for raw_line in resp:
                    text = raw_line.decode("utf-8").strip()
                    event = parse_sse_line(text)
                    if event is not None:
                        yield event
        except URLError as exc:
            raise ClientConnectionError(f"Could not connect to {self.url}: {exc.reason}") from exc

    def repl(self, *, session_id: str | None = None) -> None:
        """Start an interactive REPL that streams responses with AnsiRenderer.

        Prompts the user for input, invokes the local server, and
        renders the SSE event stream with ANSI colours in the terminal.
        Type an empty line or press Ctrl-C to exit.

        Args:
            session_id: Override the default session ID.
        """
        from .repl import run_repl

        sid = session_id or self.session_id

        def _stream(prompt: str, sid: str, renderer: AnsiRenderer) -> bool:
            try:
                for event in self.invoke(prompt=prompt, session_id=sid):
                    renderer.render(event)
            except ClientConnectionError as exc:
                print(f"\n{exc}", file=sys.stderr)
                return False
            finally:
                renderer.flush()
            return True

        run_repl(
            banner=f"Local Client \u2014 {self.url}",
            session_id=sid,
            stream_fn=_stream,
        )
