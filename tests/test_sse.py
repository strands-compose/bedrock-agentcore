"""Tests for SSE line parsing helpers."""

from __future__ import annotations

import logging
from unittest.mock import MagicMock, patch

import pytest

from strands_compose_agentcore.client.utils import parse_sse_line


class TestParseSseLine:
    """Tests for parse_sse_line."""

    def test_empty_string_returns_none(self) -> None:
        assert parse_sse_line("") is None

    def test_non_json_text_returns_none(self) -> None:
        assert parse_sse_line("this is not json") is None

    @patch("strands_compose_agentcore.client.utils.StreamEvent")
    def test_raw_json_without_prefix_parses(self, mock_event_cls: MagicMock) -> None:
        sentinel = MagicMock()
        mock_event_cls.from_dict.return_value = sentinel

        result = parse_sse_line('{"event": "text", "data": "hello"}')

        mock_event_cls.from_dict.assert_called_once_with({"event": "text", "data": "hello"})
        assert result is sentinel

    @patch("strands_compose_agentcore.client.utils.StreamEvent")
    def test_data_prefix_stripped_before_parsing(self, mock_event_cls: MagicMock) -> None:
        sentinel = MagicMock()
        mock_event_cls.from_dict.return_value = sentinel

        result = parse_sse_line('data: {"event": "text", "data": "hi"}')

        mock_event_cls.from_dict.assert_called_once_with({"event": "text", "data": "hi"})
        assert result is sentinel

    def test_invalid_json_returns_none_and_logs(self, caplog: pytest.LogCaptureFixture) -> None:
        with caplog.at_level(logging.DEBUG, logger="strands_compose_agentcore.client.utils"):
            result = parse_sse_line("data: {invalid json}")

        assert result is None
        assert "skipping non-JSON line" in caplog.text
