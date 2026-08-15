"""Snapshot of the one event shape this package authors.

``build_invocation_body`` shapes are pinned by equality in
``tests/client/test_body.py``; only the adapter's error event needs a snapshot
here, because clients branch on its keys.
"""

from __future__ import annotations

from strands_compose_agentcore._utils import error_event


def test_error_event_matches_the_upstream_error_schema() -> None:
    # Must stay identical to a strands-compose agent-level ERROR event so one
    # consumer branch handles both: data carries text + exception_type, and
    # nothing else is invented (no adapter-only "code" discriminator).
    event = error_event("boom", exception_type="AgentBusy", attempt=2)

    assert event.type == "error"
    assert event.agent_name == ""
    assert event.asdict()["data"] == {
        "text": "boom",
        "exception_type": "AgentBusy",
        "attempt": 2,
    }
