"""HTTP clients for invoking a local strands-compose-agentcore server.

Two clients for local development:

- :class:`LocalClient` — synchronous, zero extra dependencies (``urllib``).
  Use in scripts, CLIs, and sync test harnesses.
- :class:`AsyncLocalClient` — async, backed by ``httpx``.  Use in async
  web servers (e.g. FastAPI SSE proxies) and async test suites.

Both yield :class:`~strands_compose.StreamEvent` objects and expose a
:meth:`repl` method for interactive terminal use with
:class:`~strands_compose.AnsiRenderer`.

Example (sync)::

    from strands_compose_agentcore import LocalClient

    for event in LocalClient().invoke("Hello"):
        print(event.type, event.data)

Example (async)::

    from strands_compose_agentcore import AsyncLocalClient

    async with AsyncLocalClient() as client:
        async for event in client.invoke("Hello"):
            print(event.type, event.data)
"""

from __future__ import annotations

import asyncio
import json
import sys
from typing import TYPE_CHECKING, Literal, overload
from urllib.error import URLError
from urllib.request import Request, urlopen

import httpx

from ..types import AgentInput, ClientConnectionError
from .utils import (
    DEFAULT_SESSION_ID,
    build_invocation_body,
    parse_sse_line,
)

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator, Generator

    from strands_compose import AnsiRenderer, StreamEvent

__all__ = ["AsyncLocalClient", "LocalClient"]


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
            for event in client.invoke("Hello"):
                print(event.type, event.data)
        """
        self.url = url
        self.session_id = session_id or DEFAULT_SESSION_ID

    @overload
    def invoke(
        self,
        agent_input: AgentInput,
        *,
        session_id: str | None = ...,
        raw_output: Literal[True],
    ) -> Generator[str, None, None]: ...

    @overload
    def invoke(
        self,
        agent_input: AgentInput,
        *,
        session_id: str | None = ...,
        raw_output: Literal[False] = ...,
    ) -> Generator[StreamEvent, None, None]: ...

    @overload
    def invoke(
        self,
        agent_input: AgentInput,
        *,
        session_id: str | None = ...,
        raw_output: bool,
    ) -> Generator[StreamEvent | str, None, None]: ...

    def invoke(
        self,
        agent_input: AgentInput,
        *,
        session_id: str | None = None,
        raw_output: bool = False,
    ) -> Generator[StreamEvent | str, None, None]:
        """Send an agent input and yield streaming events.

        Opens an HTTP connection to the local server and reads SSE
        lines as they arrive.  Each valid JSON line is parsed into a
        :class:`~strands_compose.StreamEvent` and yielded.

                ``agent_input`` accepts this package's small client contract:

                * ``str`` — a plain user prompt.
                * one content block or a list of content blocks built with
                    :func:`~strands_compose_agentcore.text`,
                    :func:`~strands_compose_agentcore.image`,
                    :func:`~strands_compose_agentcore.document`, or
                    :func:`~strands_compose_agentcore.reply`.

        Args:
            agent_input: The user turn to send (see shapes above).
            session_id: Override the default session ID for this call.
            raw_output: When ``True``, yield raw decoded SSE lines
                (``str``) instead of parsed
                :class:`~strands_compose.StreamEvent` objects.  Blank
                and keepalive lines are still filtered.  Defaults to
                ``False``.

                **Note:** :meth:`repl` and all CLI commands always use
                ``raw_output=False`` (the default) because they depend
                on :class:`~strands_compose.StreamEvent` objects for
                terminal rendering.  Never pass ``raw_output=True`` to
                those callers.

        Yields:
            :class:`~strands_compose.StreamEvent` objects parsed from
            the SSE response when ``raw_output=False`` (default), or
            raw UTF-8 decoded SSE lines (``str``) when
            ``raw_output=True``.

        Raises:
            TypeError: ``agent_input`` is not a supported client input type.
            ValueError: ``agent_input`` is invalid or an empty list.
            ClientConnectionError: Could not connect to the server.
        """
        sid = session_id or self.session_id
        body_dict = build_invocation_body(agent_input)
        body = json.dumps(body_dict).encode()
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
                    if raw_output:
                        if text:
                            yield text
                    else:
                        event = parse_sse_line(text)
                        if event is not None:
                            yield event
        except URLError as exc:
            raise ClientConnectionError(f"Could not connect to {self.url}: {exc.reason}") from exc

    def __enter__(self) -> LocalClient:
        """Enter the sync context manager.

        Returns:
            The client instance.
        """
        return self

    def __exit__(self, *exc: object) -> None:
        """Exit the sync context manager.

        ``LocalClient`` opens a new connection per request so there is
        nothing to release here.  The method exists for consistency with
        :class:`AsyncLocalClient` and :class:`AgentCoreClient`.
        """

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
                for event in self.invoke(prompt, session_id=sid):
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


# ---------------------------------------------------------------------------
# Async client
# ---------------------------------------------------------------------------


class AsyncLocalClient:
    def __init__(
        self,
        url: str = _DEFAULT_URL,
        *,
        session_id: str | None = None,
        timeout: httpx.Timeout | None = None,
    ) -> None:
        """Async HTTP client for a local strands-compose-agentcore server.

        Uses ``httpx`` native async streaming — no threads, no blocking I/O.
        Suitable for async web servers (e.g. FastAPI SSE proxies) and async
        test suites.  N concurrent streams → N lightweight coroutines rather
        than N OS threads.

        The ``httpx.AsyncClient`` is **owned** by this instance.  Either use
        the ``async with`` context manager for automatic cleanup, or call
        :meth:`aclose` (or :meth:`close`) when done.

        Args:
            url: URL of the ``/invocations`` endpoint.  Defaults to
                ``http://localhost:8080/invocations``.
            session_id: Session ID for the AgentCore header.  When
                ``None`` (the default), uses ``DEFAULT_SESSION_ID``.
            timeout: ``httpx.Timeout`` override.  When ``None`` (the
                default), uses ``connect=5.0`` with no read/write/pool
                timeout so long SSE streams are never cut off.

        Attributes:
            url: Full URL of the ``/invocations`` endpoint.
            session_id: Session ID sent in the AgentCore header.

        Example::

            async with AsyncLocalClient() as client:
                async for event in client.invoke("Hello"):
                    print(event.type, event.data)
        """
        self.url = url
        self.session_id = session_id or DEFAULT_SESSION_ID
        self._http = httpx.AsyncClient(
            timeout=timeout or httpx.Timeout(connect=5.0, read=None, write=None, pool=None),
        )

    # -- invoke() overloads --------------------------------------------------

    @overload
    def invoke(
        self,
        agent_input: AgentInput,
        *,
        session_id: str | None = ...,
        raw_output: Literal[True],
    ) -> AsyncGenerator[str, None]: ...

    @overload
    def invoke(
        self,
        agent_input: AgentInput,
        *,
        session_id: str | None = ...,
        raw_output: Literal[False] = ...,
    ) -> AsyncGenerator[StreamEvent, None]: ...

    @overload
    def invoke(
        self,
        agent_input: AgentInput,
        *,
        session_id: str | None = ...,
        raw_output: bool,
    ) -> AsyncGenerator[StreamEvent | str, None]: ...

    async def invoke(
        self,
        agent_input: AgentInput,
        *,
        session_id: str | None = None,
        raw_output: bool = False,
    ) -> AsyncGenerator[StreamEvent | str, None]:
        """Send an agent input and yield streaming events asynchronously.

        Streams the SSE response from the local server line-by-line using
        ``httpx`` native async I/O — no threads are held during the stream.

        ``agent_input`` accepts this package's small client contract:

        * ``str`` — a plain user prompt.
        * one content block or a list of content blocks built with
          :func:`~strands_compose_agentcore.text`,
          :func:`~strands_compose_agentcore.image`,
          :func:`~strands_compose_agentcore.document`, or
          :func:`~strands_compose_agentcore.reply`.

        Args:
            agent_input: The user turn to send (see shapes above).
            session_id: Override the default session ID for this call.
            raw_output: When ``True``, yield raw decoded SSE lines
                (``str``) instead of parsed
                :class:`~strands_compose.StreamEvent` objects.  Blank
                and keepalive lines are still filtered.  Defaults to
                ``False``.

                **Note:** :meth:`repl` always uses ``raw_output=False``
                because :class:`~strands_compose.AnsiRenderer` requires
                :class:`~strands_compose.StreamEvent` objects.

        Yields:
            :class:`~strands_compose.StreamEvent` objects parsed from
            the SSE response when ``raw_output=False`` (default), or
            raw UTF-8 decoded SSE lines (``str``) when
            ``raw_output=True``.

        Raises:
            TypeError: ``agent_input`` is not a supported client input type.
            ValueError: ``agent_input`` is invalid or an empty list.
            ClientConnectionError: Could not connect to the server.
        """
        sid = session_id or self.session_id
        body = build_invocation_body(agent_input)
        try:
            async with self._http.stream(
                "POST",
                self.url,
                json=body,
                headers={
                    "Content-Type": "application/json",
                    "Accept": "text/event-stream",
                    _SESSION_HEADER: sid,
                },
            ) as response:
                response.raise_for_status()
                async for line in response.aiter_lines():
                    text = line.strip()
                    if raw_output:
                        if text:
                            yield text
                    else:
                        event = parse_sse_line(text)
                        if event is not None:
                            yield event
        except httpx.ConnectError as exc:
            raise ClientConnectionError(f"Could not connect to {self.url}: {exc}") from exc

    # -- Lifecycle -----------------------------------------------------------

    def close(self) -> None:
        """Close the underlying ``httpx.AsyncClient`` from a sync context.

        Schedules ``aclose()`` via :func:`asyncio.run`.  Do **not** call
        this from inside a running event loop — use :meth:`aclose` there.
        """
        asyncio.run(self._http.aclose())

    async def aclose(self) -> None:
        """Close the underlying ``httpx.AsyncClient``."""
        await self._http.aclose()

    async def __aenter__(self) -> AsyncLocalClient:
        """Enter the async context manager.

        Returns:
            The client instance.
        """
        return self

    async def __aexit__(self, *exc: object) -> None:
        """Exit the async context manager and close the HTTP client."""
        await self.aclose()

    # -- REPL ----------------------------------------------------------------

    def repl(self, *, session_id: str | None = None) -> None:
        """Start an interactive REPL that streams responses with AnsiRenderer.

        Prompts the user for input, invokes the local server, and renders
        the SSE event stream with ANSI colours in the terminal.  Type an
        empty line or press Ctrl-C to exit.

        Args:
            session_id: Override the default session ID.
        """
        from .repl import run_repl

        sid = session_id or self.session_id

        async def _stream_async(prompt: str, target_sid: str, renderer: AnsiRenderer) -> None:
            async for event in self.invoke(prompt, session_id=target_sid):
                renderer.render(event)
            renderer.flush()

        def _stream(prompt: str, target_sid: str, renderer: AnsiRenderer) -> bool:
            asyncio.run(_stream_async(prompt, target_sid, renderer))
            return True

        run_repl(
            banner=f"Local Async Client \u2014 {self.url}",
            session_id=sid,
            stream_fn=_stream,
        )
