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
import threading
from typing import Any

import urllib3
from botocore.response import StreamingBody
from urllib3 import HTTPConnectionPool
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


class _ClientSocket(socket.socket):
    """A real socket that records when its owner is waiting for data."""

    def __init__(self, sock: socket.socket) -> None:
        super().__init__(sock.family, sock.type, fileno=sock.detach())
        self.receiving = threading.Event()

    def recv_into(self, buffer: Any, nbytes: int = 0, flags: int = 0) -> int:
        self.receiving.set()
        try:
            return super().recv_into(buffer, nbytes, flags)
        finally:
            self.receiving.clear()


class _OpenSocketConnection(HTTPConnection):
    """A urllib3 connection that adopts an already-open socket instead of dialling."""

    def __init__(self, *args: Any, open_socket: socket.socket, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._open_socket = open_socket

    def connect(self) -> None:
        self.sock = self._open_socket


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
        self._server, plain = socket.socketpair()
        self._client = client = _ClientSocket(plain)
        self._server.settimeout(read_timeout)
        client.settimeout(read_timeout)
        self._server.sendall(_CHUNKED_HEADERS)
        # The same urlopen call botocore makes, over the socketpair.
        pool = HTTPConnectionPool("agentcore.test", timeout=read_timeout, open_socket=client)
        # urllib3's own HTTPConnection does not satisfy its BaseHTTPConnection
        # protocol under ty (default_socket_options variance).
        pool.ConnectionCls = _OpenSocketConnection  # ty: ignore[invalid-assignment]
        raw = pool.urlopen(
            "POST",
            "/invocations",
            body=b"{}",
            retries=False,
            preload_content=False,
            decode_content=False,
        )
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

    def wait_until_client_reads(self, timeout: float = 2.0) -> bool:
        """Block until a client thread is waiting on the socket for more data."""
        return self._client.receiving.wait(timeout)

    def client_disconnected(self, timeout: float = 1.0) -> bool:
        """Block until the client closes its end; ``False`` if it has not within ``timeout``."""
        self._server.settimeout(timeout)
        try:
            while self._server.recv(4096):  # skip the request the client sent
                pass
        except TimeoutError:
            return False
        return True

    def close(self) -> None:
        """Release the server end."""
        self._server.close()
