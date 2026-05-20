"""Session lifecycle — resolve agents, stream invocations.

Manages the per-session state: lazy agent resolution via
``load_session()`` and the streaming invocation loop that drains
the ``EventQueue`` while the entry agent runs.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from datetime import datetime, timezone

from strands.multiagent.base import MultiAgentBase
from strands.types.agent import AgentInput
from strands_compose import (
    AppConfig,
    EventQueue,
    ResolvedConfig,
    ResolvedInfra,
    StreamEvent,
    load_session,
)

from .payload import MultimodalPayloadError, describe_input

logger = logging.getLogger(__name__)

# AgentCore session ID length constraints.
_MIN_SESSION_ID_LENGTH = 33
_MAX_SESSION_ID_LENGTH = 256


def validate_session_id(session_id: str | None) -> None:
    """Validate the AgentCore session ID length.

    Args:
        session_id: The raw session ID from the runtime header.

    Raises:
        ValueError: If the session ID is outside the 33–256 char range.
    """
    if session_id is None:
        return
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


@dataclass
class SessionState:
    """Cached session state — agents and event queue for one session_id.

    Args:
        resolved: Fully resolved config with agents and entry point.
        events: Event queue wired to all agents via hooks.
        invocation_lock: Prevents concurrent agent invocations within
            the same session.  AgentCore Runtime allocates one microVM
            per session, but nothing prevents the caller from sending
            a second ``/invocations`` before the first one finishes.
    """

    resolved: ResolvedConfig
    events: EventQueue
    invocation_lock: asyncio.Lock = field(default_factory=asyncio.Lock)


def resolve_session(
    app_config: AppConfig,
    infra: ResolvedInfra,
    session_id: str | None,
) -> SessionState:
    """Create agents and wire the event queue for a session.

    Args:
        app_config: Validated config from YAML.
        infra: Shared infrastructure (models, MCP, session manager).
        session_id: Runtime session ID from AgentCore header.

    Returns:
        A ``SessionState`` ready for invocation.
    """
    resolved = load_session(app_config, infra, session_id=session_id)
    events = resolved.wire_event_queue()
    logger.info("session_id=<%s> | session resolved, agents ready", session_id)
    return SessionState(resolved=resolved, events=events)


async def stream_invocation(
    resolved: ResolvedConfig,
    events: EventQueue,
    agent_input: AgentInput,
    *,
    invocation_timeout: float | None = None,
) -> AsyncIterator[StreamEvent]:
    """Flush stale events, invoke the entry agent, and yield events.

    Args:
        resolved: Fully resolved config with agents and entry point.
        events: The wired EventQueue shared across invocations.
        agent_input: Input passed to the entry agent.  May be a plain
            string, a ``list[ContentBlock]`` for a multimodal user
            turn, or a full :data:`~strands.types.content.Messages`
            conversation.
        invocation_timeout: Maximum seconds to wait for the agent to
            finish.  ``None`` means no timeout.

    Yields:
        StreamEvent objects as the agent runs.

    Raises:
        MultimodalPayloadError: If the entry is a
            :class:`~strands.multiagent.base.MultiAgentBase` and a
            full ``messages`` conversation was supplied — multi-agent
            entries only accept ``str`` or ``list[ContentBlock]``.
    """
    events.flush()

    if resolved.entry is None:
        raise RuntimeError("entry point not set in resolved config")

    if (
        isinstance(resolved.entry, MultiAgentBase)
        and isinstance(agent_input, list)
        and agent_input
        and isinstance(agent_input[0], dict)
        and "role" in agent_input[0]
    ):
        raise MultimodalPayloadError(
            "multi-agent entry does not accept 'messages' input; use 'prompt' or 'content'"
        )

    input_description = describe_input(agent_input)

    async def _run() -> None:
        try:
            coro = resolved.entry.invoke_async(agent_input)  # ty: ignore[invalid-argument-type]
            if invocation_timeout is not None:
                await asyncio.wait_for(coro, timeout=invocation_timeout)
            else:
                await coro
        except TimeoutError:
            logger.error(
                "input=<%s>, timeout=<%s> | agent invocation timed out",
                input_description,
                invocation_timeout,
            )
            events.put_event(
                StreamEvent(
                    type="error",
                    agent_name="",
                    timestamp=datetime.now(tz=timezone.utc),
                    data={
                        "message": "agent invocation timed out after %s seconds"
                        % invocation_timeout
                    },
                )
            )
        except Exception:
            logger.exception("input=<%s> | agent invocation failed", input_description)
            events.put_event(
                StreamEvent(
                    type="error",
                    agent_name="",
                    timestamp=datetime.now(tz=timezone.utc),
                    data={"message": "internal error during agent invocation"},
                )
            )
        finally:
            await events.close()

    task = asyncio.create_task(_run())
    while (event := await events.get()) is not None:
        yield event
    await task
