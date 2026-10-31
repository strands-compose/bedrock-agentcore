"""Hand-written fakes for transport seams.

Only the seams our code actually touches are faked here.  boto3 is driven
through ``botocore.Stubber`` (which validates request shapes against the real
service model) rather than a hand-rolled client fake, and ``httpx`` through
``httpx.MockTransport`` -- both live inline in the client tests.  This module
holds the transport doubles with no vendor test seam:

* the ``urllib`` response object that ``LocalClient`` iterates;
* the streaming body that ``invoke_agent_runtime`` returns.  botocore wraps a
  real ``urllib3.HTTPResponse`` in a ``StreamingBody``; the builders below do
  the same, so ``AgentCoreClient`` reads through the real urllib3 stack.
"""

from __future__ import annotations

import io
import json
import socket
from typing import Any

import urllib3
from botocore.response import StreamingBody
from urllib3.connection import HTTPConnection

_CHUNKED_HEADERS = (
    b"HTTP/1.1 200 OK\r\nContent-Type: text/event-stream\r\nTransfer-Encoding: chunked\r\n\r\n"
)


class FakeUrlResponse:
    """Stands in for the urllib response context manager.

    Provides iteration over pre-loaded byte lines -- the only protocol
    ``LocalClient`` uses on the ``urlopen`` return value.
    """

    def __init__(self, lines: list[bytes]) -> None:
        self._lines = lines

    def __enter__(self):
        return self

    def __exit__(self, *exc: object):
        pass

    def __iter__(self):
        return iter(self._lines)


def sse_line(event_type: str = "token", **data: Any) -> str:
    """One SSE ``data:`` line carrying a StreamEvent dict."""
    return "data: " + json.dumps({"type": event_type, "agent_name": "a", "data": data})


def streaming_body(content: io.BytesIO) -> StreamingBody:
    """A response already received in full, wrapped as botocore wraps it.

    Returns:
        A real ``StreamingBody`` over a real ``urllib3.HTTPResponse`` reading
        from ``content``; ``content.tell()`` shows how much the client read.
    """
    return StreamingBody(urllib3.HTTPResponse(body=content, preload_content=False), None)


def sse_body(*lines: str) -> StreamingBody:
    """A complete SSE response carrying the given lines, newline-terminated."""
    return streaming_body(io.BytesIO("".join(f"{line}\n" for line in lines).encode("utf-8")))


class LiveSSEStream:
    """An open chunked SSE response that the test feeds while the client reads.

    The client side is a real ``urllib3.HTTPResponse`` over one end of a
    socketpair, wrapped in a ``StreamingBody`` exactly as botocore returns it.
    The test plays the server on the other end, so reads block on a real
    socket and shutdown/close behave as they do against AWS.

    The client socket has a read timeout so that a regression which leaves a
    read blocked fails the test instead of hanging the suite.
    """

    def __init__(self, *, read_timeout: float = 5.0) -> None:
        self._server, client = socket.socketpair()
        self._server.settimeout(read_timeout)
        client.settimeout(read_timeout)
        # urllib3 builds the response from its own connection, as it does for
        # botocore; a preset socket skips the TCP connect.
        connection = HTTPConnection("agentcore.test", timeout=read_timeout)
        connection.sock = client
        connection.request(
            "POST", "/invocations", body=b"{}", preload_content=False, decode_content=False
        )
        self._server.sendall(_CHUNKED_HEADERS)
        raw = connection.getresponse()
        self.body = StreamingBody(raw, None)

    def send(self, *lines: str) -> None:
        """Send one SSE event per line, each in its own HTTP chunk (as AgentCore does)."""
        for line in lines:
            payload = f"{line}\n\n".encode()
            self._server.sendall(b"%x\r\n%s\r\n" % (len(payload), payload))

    def end(self) -> None:
        """Finish the response cleanly."""
        self._server.sendall(b"0\r\n\r\n")

    def drop(self) -> None:
        """Cut the connection mid-chunk, as a network failure does."""
        self._server.sendall(b"ff\r\ndata: {")
        self._server.close()

    def client_disconnected(self) -> bool:
        """Block until the client closes its end; ``False`` on timeout."""
        try:
            return self._server.recv(1) == b""
        except TimeoutError:
            return False

    def close(self) -> None:
        """Release the server end."""
        self._server.close()
