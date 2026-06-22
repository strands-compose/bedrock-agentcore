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
from typing import Any

from strands.agent import AgentResult
from strands.multiagent import MultiAgentResult
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


def _session_end_data(response: AgentResult | MultiAgentResult | None) -> dict[str, Any]:
    """Build the SESSION_END payload from the entry node's final response.

    ``text`` is the plain-text answer; ``result`` is the full
    JSON-serializable strands object. For a ``MultiAgentResult`` the text
    is taken from the last contained ``AgentResult``. Empty when
    ``response`` is ``None`` (invocation raised before returning).
    """
    if response is None:
        return {"text": "", "result": {}}
    if isinstance(response, AgentResult):
        text = str(response)
    else:
        agent_results = [
            agent_result
            for node_result in response.results.values()
            for agent_result in node_result.get_agent_results()
        ]
        text = str(agent_results[-1]) if agent_results else ""
    return {"text": text, "result": response.to_dict()}


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
    events = resolved.wire_event_queue(session_id=session_id)
    logger.info("session_id=<%s> | session resolved, agents ready", session_id)
    return SessionState(resolved=resolved, events=events, session_id=session_id)


async def run_entry_agent(
    resolved: ResolvedConfig,
    events: EventQueue,
    agent_input: AgentInput,
    *,
    invocation_timeout: float | None = None,
) -> None:
    """Drive the entry agent and stream its events onto the queue.

    Awaits ``resolved.entry.invoke_async(agent_input)``, emits one error
    ``StreamEvent`` on timeout or unhandled exception, and always closes
    ``events`` so the consumer's drain loop terminates.
    ``CancelledError``, ``KeyboardInterrupt``, and ``SystemExit`` propagate
    after the close runs.

    Args:
        resolved: Fully resolved config; ``resolved.entry`` is the entry agent.
        events: The session's wired ``EventQueue``.
        agent_input: User turn forwarded to the entry agent.
        invocation_timeout: Max seconds to wait; ``None`` disables the timeout.

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
    response: AgentResult | MultiAgentResult | None = None

    try:
        coro = resolved.entry.invoke_async(agent_input)  # ty: ignore
        response = await asyncio.wait_for(coro, timeout=invocation_timeout)
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
                "Internal error during agent invocation",
                error=str(e),
            )
        )
    finally:
        # Include the entry node's final response in the SESSION_END event.
        # ``response`` is None when the invocation raised before returning.
        await events.close(data=_session_end_data(response))
