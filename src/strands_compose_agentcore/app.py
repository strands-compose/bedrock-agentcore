"""BedrockAgentCore app factory for strands-compose agents.

The config is parsed and validated once at boot.  Everything live — models,
MCP clients, agents, orchestrations — is built per session by
``load(app_config, session_id=...)`` on the first invocation, using the
session ID from the ``X-Amzn-Bedrock-AgentCore-Runtime-Session-Id`` header.
Follow-up turns reuse the cached agents and ``EventQueue``; a new session ID
closes the cached session and replaces it.

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
from strands_compose import AppConfig, load_config

from ._utils import error_event, validate_session_id
from .payload import MultimodalPayloadError, parse_payload
from .session import close_session, resolve_session, run_entry_agent

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Lifespan
# ---------------------------------------------------------------------------


def _make_lifespan(app_config: AppConfig) -> StatelessLifespan[BedrockAgentCoreApp]:
    """Return an ASGI lifespan that stashes the validated config on app state.

    No teardown: on process exit an MCP client's stdio subprocess dies with the
    parent, so there is nothing left to release.

    Args:
        app_config: Validated AppConfig from YAML.

    Returns:
        An ASGI lifespan context manager.
    """

    @asynccontextmanager
    async def _lifespan(app: BedrockAgentCoreApp) -> AsyncIterator[None]:
        app.state.app_config = app_config
        app.state.session = None  # lazily populated on first invoke

        logger.info("config validated, waiting for first invocation")
        yield

    return _lifespan


# ---------------------------------------------------------------------------
# App factory
# ---------------------------------------------------------------------------


def create_app(
    config: str | Path | list[str | Path] | AppConfig,
    *,
    cors_origins: list[str] | None = None,
    suppress_runtime_logging: bool = False,
    invocation_timeout: float | None = None,
    max_payload_bytes: int | None = 25 * 1024 * 1024,
    max_media_bytes: int = 20 * 1024 * 1024,
    max_media_blocks: int = 20,
) -> BedrockAgentCoreApp:
    """Create a BedrockAgentCoreApp with full event streaming.

    Args:
        config: YAML file path, raw YAML string, list of either, or a
            pre-built AppConfig.  Strings are auto-detected as file
            paths if the file exists, otherwise parsed as inline YAML.
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
    app_config = config if isinstance(config, AppConfig) else load_config(config)

    app = BedrockAgentCoreApp(lifespan=_make_lifespan(app_config))

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

        Resolves the session on the first call and caches it; later calls with
        the same session ID reuse it. Concurrent invocations within a session
        are rejected with an error event, and ``/ping`` reports
        ``HEALTHY_BUSY`` while an invocation runs so AgentCore Runtime backs off.

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
            yield error_event(str(exc), exception_type=type(exc).__name__).asdict()
            return

        session_id = BedrockAgentCoreContext.get_session_id()

        try:
            validate_session_id(session_id)
        except ValueError as exc:
            logger.warning("session_id=<%s> | %s", session_id, exc)
            yield error_event(str(exc), exception_type=type(exc).__name__).asdict()
            return

        # Snapshot the cached session once.  asyncio is single-threaded,
        # so the snapshot stays valid until we explicitly reassign
        # ``app.state.session`` below.
        cached = app.state.session

        # Reject if a prior invocation is still running.  The lock lives on the
        # cached SessionState — the one occupying the runtime.  Only one session
        # can occupy the runtime at a time, so a new session ID arriving
        # mid-invocation is rejected too.
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
            yield error_event(
                "Agent is already running, try again later",
                exception_type="AgentBusy",
            ).asdict()
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
                close_session(cached)
                app.state.session = None
            try:
                session = resolve_session(app.state.app_config, session_id)
            except Exception as exc:
                logger.exception("session_id=<%s> | session resolution failed", session_id)
                yield error_event(str(exc), exception_type=type(exc).__name__).asdict()
                return
            app.state.session = session

        # Drop the previous turn's SESSION_END and sentinel, then open this turn
        # so every invocation cycle streams the same lifecycle sequence.
        session.events.flush()
        session.events.emit_session_start(session.manifest)

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
