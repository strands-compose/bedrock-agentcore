"""Session lifecycle — resolve agents, run entry agent invocations.

Manages the per-session state: lazy agent resolution via
``load_session()`` and the module-level ``run_entry_agent`` coroutine
that drives the entry agent and places events on the ``EventQueue``.
"""

from __future__ import annotations

import asyncio
import logging
import math
from dataclasses import dataclass, field

from strands.types.agent import AgentInput
from strands_compose import (
    AppConfig,
    EventQueue,
    ResolvedConfig,
    ResolvedInfra,
    load_session,
)

from ._utils import error_event

logger = logging.getLogger(__name__)


@dataclass
class SessionState:
    """Cached session state — agents and event queue for one session_id.

    Args:
        resolved: Fully resolved config with agents and entry point.
        events: Event queue wired to all agents via hooks.
        session_id: The AgentCore runtime session ID this state was
            resolved for.  Used by the cache-decision logic to detect
            whether an incoming request matches the cached session.
        invocation_lock: Prevents concurrent agent invocations within
            the same session.  AgentCore Runtime allocates one microVM
            per session, but nothing prevents the caller from sending
            a second ``/invocations`` before the first one finishes.
    """

    resolved: ResolvedConfig
    events: EventQueue
    session_id: str | None = None
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
    return SessionState(resolved=resolved, events=events, session_id=session_id)


async def run_entry_agent(
    resolved: ResolvedConfig,
    events: EventQueue,
    agent_input: AgentInput,
    *,
    invocation_timeout: float | None = None,
) -> None:
    """Drive the entry agent and place events on the queue.

    Awaits ``resolved.entry.invoke_async(agent_input)``, optionally
    wrapped in ``asyncio.wait_for`` when ``invocation_timeout`` is set.
    On timeout or unhandled exception, places exactly one error
    ``StreamEvent`` on ``events``. Always closes ``events`` in
    ``finally`` so the consumer's drain loop terminates.

    ``CancelledError``, ``KeyboardInterrupt``, and ``SystemExit`` are
    not caught and propagate to the caller after the ``finally`` runs.

    Args:
        resolved: Fully resolved config; ``resolved.entry.invoke_async``
            is the entry agent.
        events: The session's wired ``EventQueue``.
        agent_input: User turn forwarded to the entry agent.
        invocation_timeout: Maximum seconds to wait. ``None`` means no
            timeout. Must be a positive finite float when provided.

    Raises:
        ValueError: ``invocation_timeout`` is zero, negative, or NaN.
    """
    if invocation_timeout is not None and (
        math.isnan(invocation_timeout) or invocation_timeout <= 0
    ):
        raise ValueError(
            "invocation_timeout must be positive and finite, got <%s>" % invocation_timeout
        )

    input_kind = type(agent_input).__name__

    try:
        coro = resolved.entry.invoke_async(agent_input)  # ty: ignore
        if invocation_timeout is not None:
            await asyncio.wait_for(coro, timeout=invocation_timeout)
        else:
            await coro
    except asyncio.TimeoutError:
        logger.error(
            "input_kind=<%s>, timeout=<%s> | agent invocation timed out",
            input_kind,
            invocation_timeout,
        )
        events.put_event(
            error_event("Agent invocation timed out after %s seconds" % invocation_timeout)
        )
    except (asyncio.CancelledError, KeyboardInterrupt, SystemExit):
        raise
    except Exception as e:
        logger.exception("input_kind=<%s> | agent invocation failed", input_kind)
        events.put_event(
            error_event(
                "internal error during agent invocation",
                error=str(e),
            )
        )
    finally:
        await events.close()
