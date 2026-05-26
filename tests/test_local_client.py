"""Tests for LocalClient and AsyncLocalClient — sync and async local SSE clients."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch
from urllib.error import URLError

import httpx
import pytest
from strands_compose import StreamEvent

from strands_compose_agentcore.client.local import AsyncLocalClient, LocalClient
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


class TestLocalClientContextManager:
    def test_enter_returns_self(self) -> None:
        client = LocalClient()
        assert client.__enter__() is client

    def test_exit_is_noop(self) -> None:
        client = LocalClient()
        # Must not raise regardless of exc info
        client.__exit__(None, None, None)

    def test_with_statement(self) -> None:
        with LocalClient() as client:
            assert isinstance(client, LocalClient)


# ---------------------------------------------------------------------------
# Helpers for AsyncLocalClient tests
# ---------------------------------------------------------------------------


def _make_async_stream_cm(lines: list[str]) -> MagicMock:
    """Build a mock for httpx.AsyncClient.stream() context manager.

    Returns a MagicMock that, when used as ``async with client.stream(...)``,
    yields a response whose ``aiter_lines()`` returns the given lines.
    """
    response = MagicMock()
    response.raise_for_status = MagicMock()

    async def _aiter_lines():
        for line in lines:
            yield line

    response.aiter_lines = _aiter_lines

    stream_cm = MagicMock()
    stream_cm.__aenter__ = AsyncMock(return_value=response)
    stream_cm.__aexit__ = AsyncMock(return_value=False)
    return stream_cm


def _sse_line(event_type: str, data: dict[str, str] | None = None) -> str:
    """Build one SSE line as a str (as httpx aiter_lines yields)."""
    event = StreamEvent(type=event_type, agent_name="local", data=data or {})
    return f"data: {json.dumps(event.asdict())}"


class TestAsyncLocalClientInit:
    def test_defaults(self) -> None:
        client = AsyncLocalClient()
        assert client.url == "http://localhost:8080/invocations"
        assert client.session_id == "default-session-strands-compose-agentcore"

    def test_custom_url_and_session(self) -> None:
        client = AsyncLocalClient("http://localhost:9000/invocations", session_id="my-sess")
        assert client.url == "http://localhost:9000/invocations"
        assert client.session_id == "my-sess"

    def test_custom_timeout(self) -> None:
        timeout = httpx.Timeout(connect=10.0, read=30.0, write=None, pool=None)
        client = AsyncLocalClient(timeout=timeout)
        assert client._http.timeout == timeout


class TestAsyncLocalClientInvoke:
    async def test_invoke_yields_events_and_skips_noise(self) -> None:
        client = AsyncLocalClient(url="http://localhost:9000/invocations", session_id="sess-1")
        stream_cm = _make_async_stream_cm(
            [
                "",
                "not-json",
                _sse_line("token", {"text": "hi"}),
            ]
        )

        with patch.object(client._http, "stream", return_value=stream_cm) as mock_stream:
            events = [event async for event in client.invoke("hello")]

        assert len(events) == 1
        assert events[0].type == "token"
        assert events[0].data == {"text": "hi"}

        mock_stream.assert_called_once()
        call_kwargs = mock_stream.call_args
        assert call_kwargs.args[0] == "POST"
        assert call_kwargs.args[1] == "http://localhost:9000/invocations"
        assert call_kwargs.kwargs["json"] == {"prompt": "hello"}
        headers = call_kwargs.kwargs["headers"]
        assert headers["X-Amzn-Bedrock-AgentCore-Runtime-Session-Id"] == "sess-1"

    async def test_invoke_overrides_session_id(self) -> None:
        client = AsyncLocalClient(session_id="default-sess")
        stream_cm = _make_async_stream_cm([_sse_line("complete")])

        with patch.object(client._http, "stream", return_value=stream_cm) as mock_stream:
            _ = [event async for event in client.invoke("hello", session_id="override-sess")]

        headers = mock_stream.call_args.kwargs["headers"]
        assert headers["X-Amzn-Bedrock-AgentCore-Runtime-Session-Id"] == "override-sess"

    async def test_invoke_raises_connection_error(self) -> None:
        client = AsyncLocalClient(url="http://localhost:7777/invocations")

        with patch.object(
            client._http,
            "stream",
            side_effect=httpx.ConnectError("connection refused"),
        ):
            with pytest.raises(
                ClientConnectionError,
                match="Could not connect to http://localhost:7777/invocations",
            ):
                async for _ in client.invoke("hello"):
                    pass

    async def test_invoke_raw_output_yields_str_lines(self) -> None:
        client = AsyncLocalClient()
        stream_cm = _make_async_stream_cm(
            [
                _sse_line("agent_start"),
                _sse_line("token", {"text": "hi"}),
            ]
        )

        with patch.object(client._http, "stream", return_value=stream_cm):
            results = [item async for item in client.invoke("hello", raw_output=True)]

        assert len(results) == 2
        assert all(isinstance(r, str) for r in results)

    async def test_invoke_raw_output_skips_blank_lines(self) -> None:
        client = AsyncLocalClient()
        stream_cm = _make_async_stream_cm(
            [
                "",
                "   ",
                _sse_line("token", {"text": "hi"}),
                "",
            ]
        )

        with patch.object(client._http, "stream", return_value=stream_cm):
            results = [item async for item in client.invoke("hello", raw_output=True)]

        assert len(results) == 1
        assert "token" in results[0]

    async def test_invoke_rejects_empty_list(self) -> None:
        client = AsyncLocalClient()
        with pytest.raises(ValueError, match="invalid agent_input"):
            async for _ in client.invoke([]):
                pass

    async def test_invoke_rejects_wrong_type(self) -> None:
        client = AsyncLocalClient()
        with pytest.raises(ValueError, match="invalid agent_input"):
            async for _ in client.invoke(123):  # ty: ignore
                pass

    async def test_invoke_with_content_blocks(self) -> None:
        client = AsyncLocalClient(session_id="sess-1")
        stream_cm = _make_async_stream_cm([_sse_line("complete")])
        blocks: list[ContentBlock] = [text("describe"), image(b"data", format="png")]

        with patch.object(client._http, "stream", return_value=stream_cm) as mock_stream:
            _ = [event async for event in client.invoke(blocks)]

        assert mock_stream.call_args.kwargs["json"] == {"prompt": blocks}


class TestAsyncLocalClientLifecycle:
    async def test_aclose_calls_http_aclose(self) -> None:
        client = AsyncLocalClient()
        with patch.object(client._http, "aclose", new_callable=AsyncMock) as mock_aclose:
            await client.aclose()
        mock_aclose.assert_called_once()

    async def test_aenter_returns_self(self) -> None:
        client = AsyncLocalClient()
        with patch.object(client._http, "aclose", new_callable=AsyncMock):
            async with client as ctx:
                assert ctx is client

    async def test_aexit_calls_aclose(self) -> None:
        client = AsyncLocalClient()
        with patch.object(client._http, "aclose", new_callable=AsyncMock) as mock_aclose:
            async with client:
                pass
        mock_aclose.assert_called_once()

    def test_close_calls_asyncio_run(self) -> None:
        client = AsyncLocalClient()
        with (
            patch.object(client._http, "aclose", new_callable=AsyncMock),
            patch("strands_compose_agentcore.client.local.asyncio.run") as mock_run,
        ):
            client.close()
        mock_run.assert_called_once()


class TestAsyncLocalClientRepl:
    def test_repl_renders_stream_and_flushes(self) -> None:
        client = AsyncLocalClient()
        event = StreamEvent(type="token", agent_name="local", data={"text": "ok"})

        async def _fake_invoke(prompt: str, *, session_id: str | None = None):
            yield event

        with (
            patch.object(client, "invoke", side_effect=_fake_invoke),
            patch("strands_compose_agentcore.client.repl.AnsiRenderer") as mock_renderer_cls,
            patch("builtins.input", side_effect=["hello", ""]),
        ):
            renderer = mock_renderer_cls.return_value
            client.repl(session_id="sid-1")

        renderer.render.assert_called_once_with(event)
        renderer.flush.assert_called_once()

    def test_repl_stops_on_eof(self) -> None:
        client = AsyncLocalClient()

        with (
            patch("strands_compose_agentcore.client.repl.AnsiRenderer"),
            patch("builtins.input", side_effect=EOFError),
            patch.object(client, "invoke") as mock_invoke,
        ):
            client.repl()

        mock_invoke.assert_not_called()


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
