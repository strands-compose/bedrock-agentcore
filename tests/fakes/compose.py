"""Hand-written fakes for strands-compose seams.

Provides FakeEntry, FakeResolvedConfig, and FakeSessionState that stand in
for strands-compose resolution and agent execution so tests never hit a real
model, MCP server, or network.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any

from strands_compose import EventQueue


class FakeEntry:
    """Stands in for a resolved entry agent/orchestration.

    ``invoke_async`` returns immediately with a canned result, or raises
    a configured exception.  No real model call, no real strands Agent.
    """

    def __init__(
        self,
        *,
        result: Any = None,
        error: Exception | None = None,
        delay: float = 0,
    ) -> None:
        self.result = result
        self.error = error
        self.delay = delay
        self.calls: list[Any] = []

    async def invoke_async(self, agent_input: Any) -> Any:
        """Fake invocation that stores the call and returns or raises."""
        self.calls.append(agent_input)
        if self.delay:
            await asyncio.sleep(self.delay)
        if self.error:
            raise self.error
        return self.result


@dataclass
class FakeResolvedConfig:
    """Minimal stand-in for strands_compose.ResolvedConfig.

    Only the fields our adapter actually reads are present:
    ``entry``, ``agents``, ``orchestrators``.
    """

    entry: FakeEntry = field(default_factory=FakeEntry)
    agents: dict[str, Any] = field(default_factory=dict)
    orchestrators: dict[str, Any] = field(default_factory=dict)

    def wire_event_queue(self, session_id: str | None = None, **kwargs: Any) -> EventQueue:
        """Return a real EventQueue wired to nothing (no hooks to fire)."""
        return EventQueue(asyncio.Queue(), session_id=session_id)


@dataclass
class FakeSessionState:
    """Pre-built SessionState for app entrypoint tests.

    Pre-loaded with a FakeResolvedConfig and a real EventQueue so the
    entrypoint can drain events without hitting strands-compose.
    """

    resolved: FakeResolvedConfig = field(default_factory=FakeResolvedConfig)
    events: EventQueue = field(default_factory=lambda: EventQueue(asyncio.Queue()))
    session_id: str | None = "test-session-id-that-is-long-enough-for-validation"
    invocation_lock: asyncio.Lock = field(default_factory=asyncio.Lock)
