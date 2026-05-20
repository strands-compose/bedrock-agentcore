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
import random
from concurrent.futures import ThreadPoolExecutor
from contextlib import suppress
from typing import TYPE_CHECKING, Any

from .._utils import validate_session_id
from ..types import AgentInput, RetryConfig, ThrottledError
from .repl import run_repl
from .utils import (
    DEFAULT_SESSION_ID,
    build_invocation_body,
    parse_sse_line,
    translate_error,
)

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator

    import boto3
    from strands_compose import AnsiRenderer, StreamEvent

logger = logging.getLogger(__name__)


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
                Each active stream holds one thread while reading the
                SSE response.
            retry: Retry configuration for throttled requests.
                ``None`` disables retry (default).  Pass
                ``RetryConfig()`` for sensible defaults.

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

        self._client = self._session.client("bedrock-agentcore", **client_kwargs)

    # -- Public API ----------------------------------------------------------

    async def invoke(
        self,
        agent_input: AgentInput,
        *,
        session_id: str,
    ) -> AsyncGenerator[StreamEvent, None]:
        """Invoke the agent runtime and yield streaming events.

        Sends a JSON payload to the deployed agent, then reads the SSE
        response stream and yields
        :class:`~strands_compose.StreamEvent` objects one at a time.

        ``agent_input`` accepts this package's small client contract:

        * ``str`` — a plain user prompt.
        * one content block or a list of content blocks built with
          :func:`~strands_compose_agentcore.text`,
          :func:`~strands_compose_agentcore.image`,
          :func:`~strands_compose_agentcore.document`, or
          :func:`~strands_compose_agentcore.reply`.

        Args:
            agent_input: The user turn to send (see shapes above).
            session_id: AgentCore session identifier (33-256 chars).

        Yields:
            StreamEvent objects parsed from the response stream.

        Raises:
            ValueError: Session ID outside the 33-256 char range, or
                ``agent_input`` is not a supported shape.
            AccessDeniedError: Credentials lack required permissions.
            ThrottledError: Request was rate-limited.
            AgentCoreClientError: Any other service error (includes AWS
                error code and message).
        """
        validate_session_id(session_id)
        body = build_invocation_body(agent_input)
        loop = asyncio.get_running_loop()

        for attempt in range(1 + self._retry.max_retries):
            try:
                response = await loop.run_in_executor(
                    self._executor, self._invoke_sync, session_id, body
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

        stream_body = response["response"]  # botocore StreamingBody
        queue: asyncio.Queue[bytes | None] = asyncio.Queue()

        def _producer() -> None:
            try:
                for line in stream_body.iter_lines():
                    loop.call_soon_threadsafe(queue.put_nowait, line)
            finally:
                loop.call_soon_threadsafe(queue.put_nowait, None)

        producer_future = loop.run_in_executor(self._executor, _producer)
        try:
            while True:
                line = await queue.get()
                if line is None:
                    break
                text = line.decode("utf-8").strip()
                event = parse_sse_line(text)
                if event is not None:
                    yield event
        finally:
            close = getattr(stream_body, "close", None)
            if callable(close):
                with suppress(Exception):
                    close()
            with suppress(Exception):
                await producer_future

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
        validate_session_id(sid)

        async def _stream_async(prompt: str, target_sid: str, renderer: AnsiRenderer) -> None:
            async for event in self.invoke(prompt, session_id=target_sid):
                renderer.render(event)
            renderer.flush()

        def _stream(prompt: str, target_sid: str, renderer: AnsiRenderer) -> bool:
            asyncio.run(_stream_async(prompt, target_sid, renderer))
            return True

        run_repl(
            banner=f"AgentCore Client \u2014 {self.agent_runtime_arn}",
            session_id=sid,
            stream_fn=_stream,
        )

    # -- Private helpers -----------------------------------------------------

    def _invoke_sync(
        self,
        session_id: str,
        body: dict[str, Any],
    ) -> dict[str, Any]:
        """Execute the synchronous boto3 invoke_agent_runtime call.

        Translates botocore ``ClientError`` into typed exceptions.
        Called via ``run_in_executor`` from :meth:`invoke`.
        """
        from botocore.exceptions import ClientError

        try:
            return self._client.invoke_agent_runtime(
                agentRuntimeArn=self.agent_runtime_arn,
                payload=json.dumps(body).encode(),
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
