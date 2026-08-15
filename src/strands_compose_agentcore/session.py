"""Per-session state: resolution, teardown, and entry-agent invocation."""

from __future__ import annotations

import asyncio
import logging
import math
from dataclasses import dataclass, field
from typing import Any

from strands import Agent
from strands.agent import AgentResult
from strands.multiagent import MultiAgentResult
from strands.types.agent import AgentInput
from strands_compose import (
    AppConfig,
    EventQueue,
    ResolvedConfig,
    load,
    make_event_queue,
    serialize_multiagent_result,
)
from strands_compose.manifest import build_manifest
from strands_compose.types import SessionManifest

from ._utils import error_event

logger = logging.getLogger(__name__)


def _session_end_data(response: AgentResult | MultiAgentResult | None) -> dict[str, Any]:
    """Build the SESSION_END payload from the entry node's final response.

    ``text`` is the plain-text answer from the last executing node; ``result``
    is the full JSON-serializable strands object.  Both are empty when the
    invocation raised before returning.
    """
    if response is None:
        return {"text": "", "result": {}}
    if isinstance(response, AgentResult):
        return {"text": str(response), "result": response.to_dict()}
    serialized = serialize_multiagent_result(response)
    return {"text": serialized["response"], "result": serialized}


@dataclass
class SessionState:
    """Live objects for one session ID.

    Args:
        resolved: Resolved config — agents, orchestrators, entry node.
        events: Event queue wired to every agent via hooks.
        manifest: Session topology, emitted with SESSION_START each turn.
        session_id: The AgentCore session ID this state was resolved for.
        invocation_lock: Guards against a second ``/invocations`` arriving
            before the first one finishes.
    """

    resolved: ResolvedConfig
    events: EventQueue
    manifest: SessionManifest
    session_id: str | None = None
    invocation_lock: asyncio.Lock = field(default_factory=asyncio.Lock)


def resolve_session(app_config: AppConfig, session_id: str | None) -> SessionState:
    """Build every live object for a session and wire the event queue.

    Args:
        app_config: Config validated at boot, so no YAML is re-read per session.
        session_id: Runtime session ID from the AgentCore header.

    Returns:
        A ``SessionState`` ready for invocation.
    """
    resolved = load(app_config, session_id=session_id)
    manifest = build_manifest(resolved.agents, resolved.orchestrators, resolved.entry)
    events = make_event_queue(
        resolved.agents,
        orchestrators=resolved.orchestrators,
        entry_name=manifest.entry.name,
        session_id=session_id,
    )
    logger.info("session_id=<%s> | session resolved, agents ready", session_id)
    return SessionState(
        resolved=resolved,
        events=events,
        manifest=manifest,
        session_id=session_id,
    )


def close_session(session: SessionState) -> None:
    """Release a replaced session's agents so their MCP clients stop immediately.

    Strands stops an ``MCPClient`` from ``Agent.__del__``, so dropping the last
    reference is usually enough.  It is not enough for an agent wired into a
    delegate orchestration: agent-as-tool puts it in a reference cycle, which
    refcounting cannot reap, leaving its stdio subprocess running until an
    arbitrary later cyclic-GC pass.  ``Agent.cleanup()`` releases the client
    directly.  Cleanup is best-effort: one failing agent must not block the rest.

    Only needed while the process keeps running.
    Process exit reaps the subprocess on its own.

    Orchestrators are included because a ``delegate`` orchestration is itself an
    ``Agent`` holding the same clients while never appearing in
    ``resolved.agents``.  ``Swarm`` and ``Graph`` are skipped — they are not
    agents, and their nodes are already covered.

    Args:
        session: The session being discarded.
    """
    nodes: dict[str, Any] = {**session.resolved.agents, **session.resolved.orchestrators}
    for name, node in nodes.items():
        if not isinstance(node, Agent):
            continue
        try:
            node.cleanup()
        except Exception:
            logger.warning(
                "session_id=<%s>, agent=<%s> | agent cleanup failed",
                session.session_id,
                name,
                exc_info=True,
            )


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
        resolved: Resolved config; ``resolved.entry`` is the entry agent.
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
            f"invocation_timeout must be positive and finite, got <{invocation_timeout}>"
        )

    input_kind = type(agent_input).__name__
    response: AgentResult | MultiAgentResult | None = None

    try:
        async with asyncio.timeout(invocation_timeout):
            response = await resolved.entry.invoke_async(agent_input)  # ty: ignore
    except TimeoutError:
        logger.error(
            "input_kind=<%s>, timeout=<%s> | agent invocation timed out",
            input_kind,
            invocation_timeout,
        )
        events.put_event(
            error_event(
                f"Agent invocation timed out after {invocation_timeout} seconds",
                exception_type="TimeoutError",
            )
        )
    except (asyncio.CancelledError, KeyboardInterrupt, SystemExit):
        raise
    except Exception as e:
        logger.exception("input_kind=<%s> | agent invocation failed", input_kind)
        events.put_event(
            error_event(
                f"Internal error during agent invocation: {e}",
                exception_type=type(e).__name__,
            )
        )
    finally:
        await events.close(data=_session_end_data(response))
