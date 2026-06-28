"""BedrockAgentCore app factory for strands-compose agents.

Provides :func:`create_app` — the main API for building a
``BedrockAgentCoreApp`` from a strands-compose YAML config.
Install this package and call the factory from your own entry script.

The app uses two-phase resolution:

- **Infrastructure** (models, MCP, session managers) is resolved once
  at boot via ``resolve_infra()``.
- **Session** (agents, orchestrations, entry point) is resolved once
  per session via ``load_session(config, infra, session_id=...)``.
  The session ID comes from the AgentCore runtime header
  ``X-Amzn-Bedrock-AgentCore-Runtime-Session-Id``.
- Follow-up prompts within the same session reuse the same agents and
  ``EventQueue`` — only the queue is flushed between turns.

Example::

    from strands_compose_agentcore import create_app

    app = create_app("config.yaml")
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager, suppress
from pathlib import Path
from typing import Any

from bedrock_agentcore import BedrockAgentCoreApp
from bedrock_agentcore.runtime.context import BedrockAgentCoreContext
from starlette.middleware.cors import CORSMiddleware
from starlette.types import StatelessLifespan
from strands_compose import AppConfig, ResolvedInfra
from strands_compose.manifest import build_manifest
from strands_compose.startup import validate_mcp

from ._utils import error_event, prepare_app_state, validate_session_id
from .payload import MultimodalPayloadError, parse_payload
from .session import resolve_session, run_entry_agent

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Lifespan
# ---------------------------------------------------------------------------


def _make_lifespan(
    app_config: AppConfig,
    infra: ResolvedInfra,
) -> StatelessLifespan[BedrockAgentCoreApp]:
    """Return an ASGI lifespan that starts MCP infrastructure.

    On startup the MCP lifecycle is entered (servers started, connectivity
    probed).  Agents are **not** created here — they are created lazily on
    the first invocation so the session ID from the AgentCore header can be
    forwarded to ``load_session``.

    On shutdown the MCP lifecycle context manager stops clients first, then
    servers.

    Args:
        app_config: Validated AppConfig from YAML.
        infra: Resolved infrastructure (models, MCP, session manager).

    Returns:
        An ASGI lifespan context manager.
    """

    @asynccontextmanager
    async def _lifespan(app: BedrockAgentCoreApp) -> AsyncIterator[None]:
        async with infra.mcp_lifecycle:
            report = await validate_mcp(infra)
            report.print_summary()

            app.state.app_config = app_config
            app.state.infra = infra
            app.state.session = None  # lazily populated on first invoke

            logger.info("infrastructure ready, waiting for first invocation")
            yield

    return _lifespan


# ---------------------------------------------------------------------------
# App factory
# ---------------------------------------------------------------------------


def create_app(
    config: str | Path | list[str | Path] | AppConfig,
    infra: ResolvedInfra | None = None,
    *,
    cors_origins: list[str] | None = None,
    suppress_runtime_logging: bool = False,
    invocation_timeout: float | None = None,
    max_payload_bytes: int | None = 25 * 1024 * 1024,
    max_media_bytes: int = 20 * 1024 * 1024,
    max_media_blocks: int = 20,
) -> BedrockAgentCoreApp:
    """Create a BedrockAgentCoreApp with full event streaming.

    This is the main API of strands-compose-agentcore.  Pass a YAML config
    path (or list of paths) and the factory handles ``load_config`` and
    ``resolve_infra`` internally.  For advanced use, pass a pre-built
    ``AppConfig`` and optional ``ResolvedInfra``.

    Infrastructure is resolved once at boot.  Session state (agents,
    orchestrations) is resolved lazily on the first invocation using
    the session ID from the ``X-Amzn-Bedrock-AgentCore-Runtime-Session-Id``
    header.  Follow-up prompts reuse the same session state.

    Args:
        config: YAML file path, raw YAML string, list of either, or
            a pre-built AppConfig.  Strings are auto-detected as file
            paths if the file exists, otherwise parsed as inline YAML.
        infra: Pre-resolved infrastructure.  When ``None`` (the default),
            ``resolve_infra()`` is called automatically.
        cors_origins: List of allowed CORS origins.
        suppress_runtime_logging: Remove the JSON log handler that
            ``BedrockAgentCoreApp`` installs on the
            ``bedrock_agentcore.app`` logger.  Useful in local
            development to avoid duplicate log lines.  In production
            on AgentCore Runtime, leave this ``False`` so CloudWatch
            receives structured JSON logs.
        invocation_timeout: Maximum seconds to wait for the agent to
            finish a single invocation.  ``None`` (the default) means
            no timeout — the agent runs until completion or failure.
        max_payload_bytes: Maximum JSON-serialized payload size in
            bytes.  ``None`` disables the check.  Defaults to 25 MiB,
            which leaves headroom under the AgentCore Runtime cap
            after base64 inflation.
        max_media_bytes: Maximum decoded size in bytes for any single
            image or document block.  Defaults to 20 MiB.
        max_media_blocks: Maximum number of media blocks (including
            image and document blocks) allowed across one invocation.
            Defaults to 20.

    Returns:
        Configured BedrockAgentCoreApp ready to run.
    """
    app_config, infra = prepare_app_state(config, infra)

    app = BedrockAgentCoreApp(
        lifespan=_make_lifespan(app_config, infra),
    )

    if suppress_runtime_logging:
        _log = logging.getLogger("bedrock_agentcore.app")
        _log.handlers.clear()
        _log.propagate = False

    if cors_origins:
        app.add_middleware(
            CORSMiddleware,  # type: ignore[arg-type]
            allow_origins=cors_origins,
            allow_methods=["*"],
            allow_headers=["*"],
        )

    @app.entrypoint
    async def invoke(payload: dict[str, Any]) -> AsyncIterator[dict[str, Any]]:
        """Entrypoint for ``/invocations`` POST requests.

        On the first call, resolves agents using the session ID from the
        AgentCore runtime header and caches the result.  Subsequent calls
        reuse the same agents — only the event queue is flushed.

        Concurrent invocations within the same session are rejected with
        an error event.  The ``/ping`` endpoint reports ``HEALTHY_BUSY``
        while an invocation is in progress so AgentCore Runtime can
        back off.

        Args:
            payload: Request payload.  Must contain a ``prompt`` key
                whose value is a string, a single content block dict,
                or a list of text, image, document, or reply blocks.

        Yields:
            JSON-serializable dicts, one per StreamEvent.
        """
        try:
            agent_input = parse_payload(
                payload,
                max_payload_bytes=max_payload_bytes,
                max_media_bytes=max_media_bytes,
                max_media_blocks=max_media_blocks,
            )
        except MultimodalPayloadError as exc:
            logger.warning("payload rejected | %s", exc)
            yield error_event(str(exc)).asdict()
            return

        session_id = BedrockAgentCoreContext.get_session_id()

        try:
            validate_session_id(session_id)
        except ValueError as exc:
            logger.warning("session_id=<%s> | %s", session_id, exc)
            yield error_event(str(exc)).asdict()
            return

        # Snapshot the cached session once.  asyncio is single-threaded,
        # so the snapshot stays valid until we explicitly reassign
        # ``app.state.session`` below.
        cached = app.state.session

        # Reject if a prior invocation is still running.  The lock
        # lives on the cached SessionState — the one currently loaded
        # into shared infrastructure (MCP, models).  A new session_id
        # arriving mid-invocation is rejected too: only one session
        # can occupy the runtime at a time.
        #
        # SAFETY: no await exists between this check and the
        # ``async with session.invocation_lock`` acquire below, so no
        # other coroutine can flip the lock state in between.
        if cached is not None and cached.invocation_lock.locked():
            logger.warning(
                "session_id=<%s>, busy_session_id=<%s> | invocation rejected, agent already running",
                session_id,
                cached.session_id,
            )
            yield error_event("Agent is already running, try again later").asdict()
            return

        if cached is not None and cached.session_id == session_id:
            session = cached
        else:
            if cached is not None:
                logger.info(
                    "session_id=<%s> | new session replaces previous session_id=<%s>",
                    session_id,
                    cached.session_id,
                )
            try:
                session = resolve_session(app.state.app_config, app.state.infra, session_id)
            except Exception as exc:
                logger.exception("session_id=<%s> | session resolution failed", session_id)
                yield error_event(str(exc)).asdict()
                return
            app.state.session = session

        # Flush stale events from any previous turn (including the SESSION_START
        # emitted by wire_event_queue on a new session, or SESSION_END + sentinel
        # left over from a cached session) and re-emit SESSION_START so every
        # invocation cycle begins with a consistent lifecycle sequence.
        session.events.flush()
        manifest = build_manifest(
            session.resolved.agents,
            session.resolved.orchestrators,
            session.resolved.entry,
        )
        session.events.emit_session_start(manifest)

        # Register the invocation as an active task so /ping returns
        # HEALTHY_BUSY while the agent is running, signalling AgentCore
        # Runtime to back off rather than send another request.
        task_id = app.add_async_task("invoke")
        try:
            async with session.invocation_lock:
                task = asyncio.create_task(
                    run_entry_agent(
                        session.resolved,
                        session.events,
                        agent_input,
                        invocation_timeout=invocation_timeout,
                    )
                )
                completed = False
                try:
                    while (event := await session.events.get()) is not None:
                        yield event.asdict()
                    completed = True
                finally:
                    if completed:
                        await task
                    else:
                        task.cancel()
                        with suppress(asyncio.CancelledError):
                            await task
        finally:
            app.complete_async_task(task_id)

    return app
