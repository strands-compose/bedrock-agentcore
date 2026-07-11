"""Snapshot-style tests asserting wire format shapes."""

from __future__ import annotations

from strands_compose_agentcore._utils import error_event
from strands_compose_agentcore.client.utils import build_invocation_body


class TestBuildInvocationBodyShape:
    """build_invocation_body output has exactly the expected keys."""

    def test_body_has_exactly_prompt_key(self) -> None:
        result = build_invocation_body("hello")
        assert set(result.keys()) == {"prompt"}

    def test_body_list_input_has_exactly_prompt_key(self) -> None:
        result = build_invocation_body([{"text": "hi"}])
        assert set(result.keys()) == {"prompt"}


class TestErrorEventShape:
    """error_event().asdict() has the expected shape."""

    def test_error_event_asdict_has_type_agent_name_data(self) -> None:
        event = error_event("something failed")
        d = event.asdict()
        assert "type" in d
        assert "agent_name" in d
        assert "data" in d
        assert d["type"] == "error"
        assert d["agent_name"] == ""

    def test_error_event_data_contains_text_key(self) -> None:
        event = error_event("oops")
        d = event.asdict()
        assert "text" in d["data"]
        assert d["data"]["text"] == "oops"

    def test_error_event_extra_kwargs_appear_in_data(self) -> None:
        event = error_event("fail", code=42)
        d = event.asdict()
        assert d["data"]["code"] == 42
