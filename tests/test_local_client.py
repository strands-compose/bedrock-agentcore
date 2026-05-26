"""Tests for LocalClient — sync local SSE client."""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch
from urllib.error import URLError

import pytest
from strands_compose import StreamEvent

from strands_compose_agentcore.client.local import LocalClient
from strands_compose_agentcore.media import image, text
from strands_compose_agentcore.types import ClientConnectionError, ContentBlock


def _event_line(event_type: str, data: dict[str, str] | None = None) -> bytes:
    """Build one SSE line as bytes."""
    event = StreamEvent(type=event_type, agent_name="local", data=data or {})
    return f"data: {json.dumps(event.asdict())}\n".encode("utf-8")


class TestLocalClientInvoke:
    def test_init_defaults(self) -> None:
        client = LocalClient()
        assert client.url == "http://localhost:8080/invocations"
        assert client.session_id == "default-session-strands-compose-agentcore"

    def test_invoke_yields_events_and_skips_noise(self) -> None:
        client = LocalClient(url="http://localhost:9000/invocations", session_id="sess-1")
        response = MagicMock()
        response.__iter__.return_value = iter(
            [
                b"\n",
                b"not-json\n",
                _event_line("token", {"text": "hi"}),
            ]
        )
        response_cm = MagicMock()
        response_cm.__enter__.return_value = response
        response_cm.__exit__.return_value = False

        with patch(
            "strands_compose_agentcore.client.local.urlopen", return_value=response_cm
        ) as mock_urlopen:
            events = list(client.invoke("hello"))

        assert len(events) == 1
        assert events[0].type == "token"
        assert events[0].data == {"text": "hi"}

        request = mock_urlopen.call_args.args[0]
        assert request.full_url == "http://localhost:9000/invocations"
        assert request.get_method() == "POST"
        assert request.data == b'{"prompt": "hello"}'
        assert request.headers["X-amzn-bedrock-agentcore-runtime-session-id"] == "sess-1"

    def test_invoke_overrides_session_id(self) -> None:
        client = LocalClient(session_id="default-sess")
        response = MagicMock()
        response.__iter__.return_value = iter([_event_line("complete")])
        response_cm = MagicMock()
        response_cm.__enter__.return_value = response
        response_cm.__exit__.return_value = False

        with patch(
            "strands_compose_agentcore.client.local.urlopen", return_value=response_cm
        ) as mock_urlopen:
            _ = list(client.invoke("hello", session_id="override-sess"))

        request = mock_urlopen.call_args.args[0]
        assert request.headers["X-amzn-bedrock-agentcore-runtime-session-id"] == "override-sess"

    def test_invoke_raises_connection_error(self) -> None:
        client = LocalClient(url="http://localhost:7777/invocations")

        with (
            patch(
                "strands_compose_agentcore.client.local.urlopen",
                side_effect=URLError("connection refused"),
            ),
            pytest.raises(
                ClientConnectionError,
                match="Could not connect to http://localhost:7777/invocations",
            ),
        ):
            _ = list(client.invoke("hello"))

    def test_invoke_with_content_sends_content_body(self) -> None:
        client = LocalClient(session_id="sess-1")
        response = MagicMock()
        response.__iter__.return_value = iter([_event_line("complete")])
        response_cm = MagicMock()
        response_cm.__enter__.return_value = response
        response_cm.__exit__.return_value = False

        blocks: list[ContentBlock] = [text("describe"), image(b"data", format="png")]
        with patch(
            "strands_compose_agentcore.client.local.urlopen", return_value=response_cm
        ) as mock_urlopen:
            _ = list(client.invoke(blocks))

        request = mock_urlopen.call_args.args[0]
        assert json.loads(request.data.decode()) == {"prompt": blocks}

    def test_invoke_with_single_block_sends_content_list(self) -> None:
        client = LocalClient(session_id="sess-1")
        response = MagicMock()
        response.__iter__.return_value = iter([_event_line("complete")])
        response_cm = MagicMock()
        response_cm.__enter__.return_value = response
        response_cm.__exit__.return_value = False

        block = text("hi")
        with patch(
            "strands_compose_agentcore.client.local.urlopen", return_value=response_cm
        ) as mock_urlopen:
            _ = list(client.invoke(block))

        request = mock_urlopen.call_args.args[0]
        assert json.loads(request.data.decode()) == {"prompt": [block]}

    def test_invoke_rejects_empty_list(self) -> None:
        client = LocalClient()
        with pytest.raises(ValueError, match="invalid agent_input"):
            next(client.invoke([]))

    def test_invoke_rejects_wrong_type(self) -> None:
        client = LocalClient()
        with pytest.raises(ValueError, match="invalid agent_input"):
            next(client.invoke(123))  # ty: ignore


class TestLocalClientInvokeRawOutput:
    def _make_response_cm(self, lines: list[bytes]) -> MagicMock:
        response = MagicMock()
        response.__iter__.return_value = iter(lines)
        response_cm = MagicMock()
        response_cm.__enter__.return_value = response
        response_cm.__exit__.return_value = False
        return response_cm

    def test_raw_output_yields_str_lines(self) -> None:
        client = LocalClient()
        response_cm = self._make_response_cm(
            [
                _event_line("agent_start"),
                _event_line("token", {"text": "hi"}),
            ]
        )
        with patch("strands_compose_agentcore.client.local.urlopen", return_value=response_cm):
            results = list(client.invoke("hello", raw_output=True))

        assert len(results) == 2
        assert all(isinstance(r, str) for r in results)

    def test_raw_output_skips_blank_lines(self) -> None:
        client = LocalClient()
        response_cm = self._make_response_cm(
            [
                b"\n",
                b"  \n",
                _event_line("token", {"text": "hi"}),
                b"\n",
            ]
        )
        with patch("strands_compose_agentcore.client.local.urlopen", return_value=response_cm):
            results = list(client.invoke("hello", raw_output=True))

        assert len(results) == 1
        assert isinstance(results[0], str)
        assert "token" in results[0]

    def test_raw_output_does_not_call_parse_sse_line(self) -> None:
        client = LocalClient()
        response_cm = self._make_response_cm([_event_line("token", {"text": "hi"})])
        with (
            patch("strands_compose_agentcore.client.local.urlopen", return_value=response_cm),
            patch("strands_compose_agentcore.client.local.parse_sse_line") as mock_parse,
        ):
            _ = list(client.invoke("hello", raw_output=True))

        mock_parse.assert_not_called()

    def test_raw_output_false_yields_stream_events(self) -> None:
        client = LocalClient()
        response_cm = self._make_response_cm([_event_line("token", {"text": "hi"})])
        with patch("strands_compose_agentcore.client.local.urlopen", return_value=response_cm):
            results = list(client.invoke("hello", raw_output=False))

        assert len(results) == 1
        assert isinstance(results[0], StreamEvent)


class TestLocalClientRepl:
    def test_repl_renders_stream_and_flushes(self) -> None:
        client = LocalClient()
        event = StreamEvent(type="token", agent_name="local", data={"text": "ok"})

        with (
            patch.object(client, "invoke", return_value=iter([event])) as mock_invoke,
            patch("strands_compose_agentcore.client.repl.AnsiRenderer") as mock_renderer_cls,
            patch("builtins.input", side_effect=["hello", ""]),
        ):
            renderer = mock_renderer_cls.return_value
            client.repl(session_id="sid-1")

        mock_invoke.assert_called_once_with("hello", session_id="sid-1")
        renderer.render.assert_called_once_with(event)
        renderer.flush.assert_called_once()

    def test_repl_stops_on_connection_error(self) -> None:
        client = LocalClient()

        with (
            patch.object(
                client, "invoke", side_effect=ClientConnectionError("boom")
            ) as mock_invoke,
            patch("strands_compose_agentcore.client.repl.AnsiRenderer") as mock_renderer_cls,
            patch("builtins.input", side_effect=["hello"]),
        ):
            renderer = mock_renderer_cls.return_value
            client.repl()

        mock_invoke.assert_called_once()
        renderer.flush.assert_called_once()

    def test_repl_stops_on_eof(self) -> None:
        client = LocalClient()

        with (
            patch("strands_compose_agentcore.client.repl.AnsiRenderer"),
            patch("builtins.input", side_effect=EOFError),
            patch.object(client, "invoke") as mock_invoke,
        ):
            client.repl()

        mock_invoke.assert_not_called()

    def test_repl_handles_keyboard_interrupt(self) -> None:
        client = LocalClient()

        with (
            patch("strands_compose_agentcore.client.repl.AnsiRenderer"),
            patch("builtins.input", side_effect=KeyboardInterrupt),
            patch.object(client, "invoke") as mock_invoke,
        ):
            client.repl()

        mock_invoke.assert_not_called()
