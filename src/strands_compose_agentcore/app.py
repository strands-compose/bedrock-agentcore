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

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from bedrock_agentcore import BedrockAgentCoreApp
from bedrock_agentcore.runtime.context import BedrockAgentCoreContext
from starlette.middleware.cors import CORSMiddleware
from starlette.types import StatelessLifespan
from strands_compose import (
    AppConfig,
    ResolvedInfra,
    StreamEvent,
    load_config,
    resolve_infra,
)
from strands_compose.startup import validate_mcp

from .session import SessionState, resolve_session, stream_invocation, validate_session_id

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
            app.state.session_id = None  # bound on first invoke

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

    Returns:
        Configured BedrockAgentCoreApp ready to run.
    """
    # Resolve config from path/string if needed.
    if isinstance(config, (str, Path, list)):
        app_config = load_config(config)
    else:
        app_config = config

    # Validate that an entry point is defined.
    if not getattr(app_config, "entry", None):
        raise ValueError(
            "config has no 'entry' defined — set 'entry: <agent_name>' in your YAML config"
        )

    # Resolve infrastructure if not provided.
    if infra is None:
        infra = resolve_infra(app_config)

    _invocation_timeout = invocation_timeout  # capture for closure

    app = BedrockAgentCoreApp(
        lifespan=_make_lifespan(app_config, infra),
    )

    if suppress_runtime_logging:
        logging.getLogger("bedrock_agentcore.app").handlers.clear()

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
            payload: Request payload.  Required key: ``prompt``.

        Yields:
            JSON-serializable dicts, one per StreamEvent.
        """
        prompt = payload.get("prompt")
        if not prompt:
            yield StreamEvent(
                type="error",
                agent_name="",
                timestamp=datetime.now(tz=timezone.utc),
                data={"message": "missing or empty required field: prompt"},
            ).asdict()
            return

        session_id = BedrockAgentCoreContext.get_session_id()

        try:
            validate_session_id(session_id)
        except ValueError as exc:
            logger.warning("session_id=<%s> | %s", session_id, exc)
            yield StreamEvent(
                type="error",
                agent_name="",
                timestamp=datetime.now(tz=timezone.utc),
                data={"message": str(exc)},
            ).asdict()
            return

        # Resolve session first (sync — no await, no context switch).
        session: SessionState | None = app.state.session
        if session is None or app.state.session_id != session_id:
            if app.state.session_id is not None:
                logger.info(
                    "session_id=<%s> | new session replaces previous session_id=<%s>",
                    session_id,
                    app.state.session_id,
                )
            session = resolve_session(
                app.state.app_config,
                app.state.infra,
                session_id,
            )
            app.state.session = session
            app.state.session_id = session_id

        # SAFETY: asyncio is single-threaded.  No await exists between
        # locked() and the async-with acquire below, so no other
        # coroutine can acquire the lock in between.
        if session.invocation_lock.locked():
            logger.warning(
                "session_id=<%s> | invocation rejected, agent already running",
                session_id,
            )
            yield StreamEvent(
                type="error",
                agent_name="",
                timestamp=datetime.now(tz=timezone.utc),
                data={"message": "agent is already running, try again later"},
            ).asdict()
            return

        task_id = app.add_async_task("invoke")
        try:
            async with session.invocation_lock:
                async for event in stream_invocation(
                    session.resolved,
                    session.events,
                    prompt,
                    invocation_timeout=_invocation_timeout,
                ):
                    yield event.asdict()
        finally:
            app.complete_async_task(task_id)

    return app
