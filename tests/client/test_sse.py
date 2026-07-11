"""Tests for parse_sse_line: valid events, blanks, and non-JSON."""

from __future__ import annotations

import json

from strands_compose import StreamEvent

from strands_compose_agentcore.client.utils import parse_sse_line


class TestParseSseLine:
    """parse_sse_line decodes SSE data lines into StreamEvent objects."""

    def test_sse_line_with_data_prefix_returns_stream_event(self) -> None:
        event_dict = {"type": "text", "agent_name": "test", "data": {"text": "hi"}}
        line = f"data: {json.dumps(event_dict)}"
        result = parse_sse_line(line)
        assert isinstance(result, StreamEvent)
        assert result.type == "text"
        assert result.agent_name == "test"

    def test_sse_blank_line_returns_none(self) -> None:
        result = parse_sse_line("")
        assert result is None

    def test_sse_non_json_line_returns_none(self) -> None:
        result = parse_sse_line("this is not json at all")
        assert result is None

    def test_sse_comment_line_returns_none(self) -> None:
        result = parse_sse_line(": keepalive")
        assert result is None

    def test_sse_valid_json_without_data_prefix_still_parses(self) -> None:
        event_dict = {"type": "text", "agent_name": "agent", "data": {"text": "hello"}}
        line = json.dumps(event_dict)
        result = parse_sse_line(line)
        assert isinstance(result, StreamEvent)
        assert result.type == "text"
