"""Hand-written fakes for strands-compose seams.

Provides FakeEntry, FakeResolvedConfig, and FakeSessionState that stand in for
strands-compose resolution and agent execution so tests never hit a real
model, MCP server, or network.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any

from strands_compose import EventQueue
from strands_compose.types import SessionManifest

from tests.factories import minimal_manifest


class FakeEntry:
    """Stands in for a resolved entry agent/orchestration.

    ``invoke_async`` returns a canned result, raises a configured error, or --
    when ``gate`` is set -- waits on that event so a test can control *when*
    the run completes.  A gate that is never set models a run that never
    finishes on its own (timeout, cancellation, busy).  No real model call,
    no real strands Agent, no clocks.
    """

    def __init__(
        self,
        *,
        result: Any = None,
        error: Exception | None = None,
        gate: asyncio.Event | None = None,
    ) -> None:
        self.result = result
        self.error = error
        self.gate = gate
        self.calls: list[Any] = []

    async def invoke_async(self, agent_input: Any) -> Any:
        """Fake invocation that stores the call and returns, raises, or gates."""
        self.calls.append(agent_input)
        if self.gate is not None:
            await self.gate.wait()
        if self.error:
            raise self.error
        return self.result


@dataclass
class FakeResolvedConfig:
    """Minimal stand-in for strands_compose.ResolvedConfig.

    Only the fields our adapter reads are present.
    """

    entry: FakeEntry = field(default_factory=FakeEntry)
    agents: dict[str, Any] = field(default_factory=dict)
    orchestrators: dict[str, Any] = field(default_factory=dict)


@dataclass
class FakeSessionState:
    """Pre-built SessionState for app entrypoint tests.

    Pre-loaded with a FakeResolvedConfig, a real EventQueue, and a real
    manifest so the entrypoint can drain events without hitting
    strands-compose.
    """

    resolved: FakeResolvedConfig = field(default_factory=FakeResolvedConfig)
    events: EventQueue = field(default_factory=lambda: EventQueue(asyncio.Queue()))
    manifest: SessionManifest = field(default_factory=minimal_manifest)
    session_id: str | None = "test-session-id-that-is-long-enough-for-validation"
    invocation_lock: asyncio.Lock = field(default_factory=asyncio.Lock)
