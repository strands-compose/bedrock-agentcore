"""Async boto3 wrapper for invoking AgentCore-deployed agents.

Provides :class:`AgentCoreClient` — a thin client that calls
``invoke_agent_runtime`` and yields
:class:`~strands_compose.StreamEvent` objects from the streaming
response.  All boto3 I/O is offloaded to a dedicated thread executor
so callers can ``async for event in client.invoke(...)`` without
blocking the event loop.

The client is safe for concurrent use from multiple coroutines (e.g.
multi-tenant FastAPI).  Each ``invoke()`` call gets its own streaming
response — no shared mutable state between sessions.  A dedicated
``ThreadPoolExecutor`` is sized to the expected number of concurrent
streams so the default executor is never starved.
"""

from __future__ import annotations

import asyncio
import json
import logging
import threading
from concurrent.futures import ThreadPoolExecutor
from typing import TYPE_CHECKING, Any

from .repl import run_repl
from .utils import (
    DEFAULT_SESSION_ID,
    AgentCoreClientError,
    RetryConfig,
    ThrottledError,
    parse_sse_line,
    translate_error,
)

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator

    import boto3
    from strands_compose import AnsiRenderer, StreamEvent

__all__ = ["AgentCoreClient"]

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_STREAM_DONE = object()  # sentinel for StopIteration in executor

# AgentCore requires session IDs of 33–256 chars.
_MIN_SESSION_ID_LENGTH = 33
_MAX_SESSION_ID_LENGTH = 256


# ---------------------------------------------------------------------------
# Client
# ---------------------------------------------------------------------------


class AgentCoreClient:
    def __init__(
        self,
        agent_runtime_arn: str,
        *,
        region: str | None = None,
        session: boto3.Session | None = None,
        timeout: float | None = None,
        max_concurrent_streams: int = 64,
        retry: RetryConfig | None = None,
    ) -> None:
        """Async wrapper around boto3 ``invoke_agent_runtime`` for streaming invocations.

        Calls the AgentCore data-plane API, reads the SSE streaming response,
        and yields :class:`~strands_compose.StreamEvent` objects.

        Safe for concurrent use from multiple coroutines — each
        ``invoke()`` call gets its own boto3 response/stream, and a
        **dedicated** ``ThreadPoolExecutor`` ensures the event loop's
        default executor is never starved by long-running SSE reads.

        Args:
            agent_runtime_arn: Full ARN of the deployed agent runtime.
            region: AWS region override.  Falls back to the boto3
                session's default region.
            session: Optional pre-configured ``boto3.Session``.
            timeout: Socket read timeout in seconds for the streaming
                response.  ``None`` uses the botocore default.
            max_concurrent_streams: Maximum number of concurrent
                ``invoke()`` calls that can stream simultaneously.
                Each active stream holds one thread while waiting
                for the next SSE event.  Set this to the expected
                peak number of concurrent tenant sessions.
            retry: Retry configuration for throttled requests.
                ``None`` disables retry (default).  Pass
                ``RetryConfig()`` for sensible defaults (3 retries,
                exponential backoff with jitter).

        Attributes:
            agent_runtime_arn: Full ARN of the deployed agent runtime.
        """
        import boto3 as _boto3

        self.agent_runtime_arn = agent_runtime_arn
        self._session = session or _boto3.Session()
        self._retry = retry or RetryConfig(max_retries=0)
        self._executor = ThreadPoolExecutor(
            max_workers=max_concurrent_streams,
            thread_name_prefix="agentcore-stream",
        )

        resolved_region = region or self._session.region_name
        if not resolved_region:
            raise ValueError(
                "No AWS region specified. Pass region= explicitly or configure "
                "a default region in your boto3 session / environment."
            )

        client_kwargs: dict[str, Any] = {"region_name": resolved_region}
        if timeout is not None:
            from botocore.config import Config

            client_kwargs["config"] = Config(read_timeout=int(timeout))

        self._client = self._session.client(
            "bedrock-agentcore",
            **client_kwargs,
        )

    # -- Public API ----------------------------------------------------------

    async def invoke(
        self,
        *,
        session_id: str,
        prompt: str,
        payload_extras: dict[str, Any] | None = None,
    ) -> AsyncGenerator[StreamEvent, None]:
        """Invoke the agent runtime and yield streaming events.

        Sends a JSON payload ``{"prompt": prompt}`` (plus any
        *payload_extras*) to the deployed agent, then reads the SSE
        response stream and yields
        :class:`~strands_compose.StreamEvent` objects one at a time.

        Args:
            session_id: AgentCore session identifier (33-256 chars).
            prompt: User message to send to the agent.
            payload_extras: Additional keys merged into the JSON payload.
                Useful for multi-modal requests (e.g. ``{"media": {...}}``).

        Yields:
            StreamEvent objects parsed from the response stream.

        Raises:
            AccessDeniedError: Credentials lack required permissions.
            ThrottledError: Request was rate-limited.
            AgentCoreClientError: Any other service error (includes AWS
                error code and message).
        """
        if len(session_id) < _MIN_SESSION_ID_LENGTH:
            raise ValueError(
                "session_id=<%s> is too short (%d chars). "
                "AgentCore requires at least %d characters."
                % (session_id, len(session_id), _MIN_SESSION_ID_LENGTH)
            )
        if len(session_id) > _MAX_SESSION_ID_LENGTH:
            raise ValueError(
                "session_id=<%s...> is too long (%d chars). "
                "AgentCore allows at most %d characters."
                % (session_id[:20], len(session_id), _MAX_SESSION_ID_LENGTH)
            )

        loop = asyncio.get_running_loop()

        import random

        for attempt in range(1 + self._retry.max_retries):
            try:
                response = await loop.run_in_executor(
                    self._executor, self._invoke_sync, session_id, prompt, payload_extras
                )
                break
            except ThrottledError:
                if attempt >= self._retry.max_retries:
                    raise
                delay = min(
                    self._retry.base_delay * (2**attempt),
                    self._retry.max_delay,
                )
                if self._retry.jitter:
                    delay += random.uniform(0, self._retry.base_delay)  # nosec B311
                logger.info(
                    "attempt=<%d>, delay=<%0.2f> | throttled, retrying",
                    attempt + 1,
                    delay,
                )
                await asyncio.sleep(delay)
            except AgentCoreClientError:
                raise
            except Exception as exc:
                raise AgentCoreClientError(str(exc)) from exc

        body = response["response"]  # botocore StreamingBody
        line_iter = body.iter_lines()

        while True:
            line = await loop.run_in_executor(self._executor, self._next_line, line_iter)
            if line is _STREAM_DONE:
                break
            if not isinstance(line, bytes):  # pragma: no cover — defensive guard
                continue
            text = line.decode("utf-8").strip()
            event = parse_sse_line(text)
            if event is not None:
                yield event

    def repl(self, *, session_id: str | None = None) -> None:
        """Start an interactive REPL that streams agent responses with AnsiRenderer.

        Prompts the user for input, invokes the deployed agent, and
        renders the SSE event stream with ANSI colours in the terminal.
        Type an empty line or press Ctrl-C to exit.

        Args:
            session_id: AgentCore session identifier.  If ``None``, uses
                ``DEFAULT_SESSION_ID``.
        """

        sid = session_id or DEFAULT_SESSION_ID
        if len(sid) < _MIN_SESSION_ID_LENGTH:
            raise ValueError(
                "session_id=<%s> is too short (%d chars). "
                "AgentCore requires at least %d characters."
                % (sid, len(sid), _MIN_SESSION_ID_LENGTH)
            )
        if len(sid) > _MAX_SESSION_ID_LENGTH:
            raise ValueError(
                "session_id=<%s...> is too long (%d chars). "
                "AgentCore allows at most %d characters."
                % (sid[:20], len(sid), _MAX_SESSION_ID_LENGTH)
            )

        loop = asyncio.new_event_loop()
        loop_thread = threading.Thread(target=loop.run_forever, daemon=True)
        loop_thread.start()

        def _stream(prompt: str, sid: str, renderer: AnsiRenderer) -> bool:
            async def _run() -> None:
                async for event in self.invoke(session_id=sid, prompt=prompt):
                    renderer.render(event)
                renderer.flush()

            future = asyncio.run_coroutine_threadsafe(_run(), loop)
            future.result()
            return True

        try:
            run_repl(
                banner=f"AgentCore Client \u2014 {self.agent_runtime_arn}",
                session_id=sid,
                stream_fn=_stream,
            )
        finally:
            loop.call_soon_threadsafe(loop.stop)
            loop_thread.join(timeout=5.0)
            loop.close()

    # -- Private helpers -----------------------------------------------------

    def _invoke_sync(
        self,
        session_id: str,
        prompt: str,
        payload_extras: dict[str, Any] | None,
    ) -> dict[str, Any]:
        """Execute the synchronous boto3 invoke_agent_runtime call.

        Translates botocore ``ClientError`` into typed exceptions.
        Called via ``run_in_executor`` from :meth:`invoke`.
        """
        from botocore.exceptions import ClientError

        payload: dict[str, Any] = {"prompt": prompt}
        if payload_extras:
            payload.update(payload_extras)

        try:
            return self._client.invoke_agent_runtime(
                agentRuntimeArn=self.agent_runtime_arn,
                payload=json.dumps(payload).encode(),
                contentType="application/json",
                accept="text/event-stream",
                runtimeSessionId=session_id,
            )
        except ClientError as exc:
            raise translate_error(exc) from exc

    async def __aenter__(self) -> AgentCoreClient:
        """Enter the async context manager.

        Returns:
            The client instance.
        """
        return self

    async def __aexit__(self, *exc: object) -> None:
        """Exit the async context manager and shut down the thread pool."""
        self.close()

    def close(self) -> None:
        """Shut down the thread pool.

        Call this when the client is no longer needed — for example in
        a FastAPI ``lifespan`` shutdown handler.  In-flight streams
        finish before the pool is torn down.
        """
        self._executor.shutdown(wait=True)

    @staticmethod
    def _next_line(line_iter: Any) -> bytes | object:
        """Advance the line iterator, returning ``_STREAM_DONE`` on exhaustion.

        ``StopIteration`` cannot propagate through
        ``run_in_executor`` — Python converts it to ``RuntimeError``
        (PEP 479).  This helper catches it and returns a sentinel instead.
        """
        try:
            return next(line_iter)
        except StopIteration:
            return _STREAM_DONE
