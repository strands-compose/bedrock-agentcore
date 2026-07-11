"""Tests for validate_session_id and error_event utilities."""

from __future__ import annotations

import pytest
from strands_compose import StreamEvent

from strands_compose_agentcore._utils import error_event, validate_session_id


class TestValidateSessionId:
    """validate_session_id enforces 33-256 char length constraints."""

    def test_validate_session_id_accepts_none(self) -> None:
        validate_session_id(None)  # should not raise

    def test_validate_session_id_accepts_33_char_string(self) -> None:
        validate_session_id("a" * 33)  # should not raise

    def test_validate_session_id_accepts_256_char_string(self) -> None:
        validate_session_id("b" * 256)  # should not raise

    def test_validate_session_id_rejects_32_char_string_as_too_short(self) -> None:
        with pytest.raises(ValueError, match="too short"):
            validate_session_id("c" * 32)

    def test_validate_session_id_rejects_257_char_string_as_too_long(self) -> None:
        with pytest.raises(ValueError, match="too long"):
            validate_session_id("d" * 257)


class TestErrorEvent:
    """error_event() returns a StreamEvent with correct fields."""

    def test_error_event_returns_stream_event_with_error_type(self) -> None:
        event = error_event("something went wrong")
        assert isinstance(event, StreamEvent)
        assert event.type == "error"
        assert event.agent_name == ""

    def test_error_event_data_contains_text_message(self) -> None:
        event = error_event("broken")
        assert event.data["text"] == "broken"

    def test_error_event_merges_extra_kwargs_into_data(self) -> None:
        event = error_event("fail", code=500, reason="timeout")
        assert event.data["code"] == 500
        assert event.data["reason"] == "timeout"
