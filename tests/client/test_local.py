"""Tests for LocalClient and AsyncLocalClient invoke contracts.

Sync tests use FakeUrlResponse (owned fake) instead of MagicMock context
managers.  Async tests use httpx.MockTransport -- a real transport
implementation the test controls.
"""

from __future__ import annotations

import json
from unittest.mock import patch
from urllib.error import URLError

import httpx
import pytest
from strands_compose import StreamEvent

from strands_compose_agentcore.client.local import AsyncLocalClient, LocalClient
from strands_compose_agentcore.types import ClientConnectionError

from tests.fakes.transport import FakeUrlResponse


class TestLocalClientInvoke:
    """LocalClient.invoke yields StreamEvent from urllib response."""

    def test_invoke_yields_stream_events(self) -> None:
        event_dict = {"type": "text", "agent_name": "agent", "data": {"text": "hi"}}
        sse_line = f"data: {json.dumps(event_dict)}\n"
        fake_response = FakeUrlResponse([sse_line.encode("utf-8")])

        with patch("strands_compose_agentcore.client.local.urlopen", return_value=fake_response):
            client = LocalClient()
            events = list(client.invoke("Hello"))

        assert len(events) == 1
        assert isinstance(events[0], StreamEvent)
        assert events[0].type == "text"

    def test_invoke_yields_multiple_events(self) -> None:
        events_data = [
            {"type": "text", "agent_name": "agent", "data": {"text": "hello"}},
            {"type": "text", "agent_name": "agent", "data": {"text": " world"}},
        ]
        lines = [f"data: {json.dumps(e)}\n".encode("utf-8") for e in events_data]
        fake_response = FakeUrlResponse(lines)

        with patch("strands_compose_agentcore.client.local.urlopen", return_value=fake_response):
            client = LocalClient()
            events = list(client.invoke("Hello"))

        assert len(events) == 2
        assert all(isinstance(e, StreamEvent) for e in events)

    def test_invoke_skips_blank_lines(self) -> None:
        event_dict = {"type": "text", "agent_name": "agent", "data": {"text": "hi"}}
        lines = [
            b"\n",
            f"data: {json.dumps(event_dict)}\n".encode("utf-8"),
            b"\n",
        ]
        fake_response = FakeUrlResponse(lines)

        with patch("strands_compose_agentcore.client.local.urlopen", return_value=fake_response):
            client = LocalClient()
            events = list(client.invoke("Hello"))

        assert len(events) == 1

    def test_invoke_raises_connection_error_on_url_error(self) -> None:
        with patch(
            "strands_compose_agentcore.client.local.urlopen",
            side_effect=URLError("Connection refused"),
        ):
            client = LocalClient()
            with pytest.raises(ClientConnectionError):
                list(client.invoke("Hello"))


class TestAsyncLocalClientInvoke:
    """AsyncLocalClient.invoke yields StreamEvent from httpx stream."""

    async def test_invoke_yields_stream_events(self) -> None:
        event_dict = {"type": "text", "agent_name": "agent", "data": {"text": "hello"}}
        sse_line = f"data: {json.dumps(event_dict)}"

        async def mock_transport(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, text=sse_line + "\n")

        transport = httpx.MockTransport(mock_transport)
        async with AsyncLocalClient() as client:
            client._http = httpx.AsyncClient(transport=transport)
            events = [event async for event in client.invoke("Hello")]

        assert len(events) == 1
        assert isinstance(events[0], StreamEvent)
        assert events[0].type == "text"

    async def test_invoke_raises_connection_error_on_connect_failure(self) -> None:
        async def mock_transport(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("refused")

        transport = httpx.MockTransport(mock_transport)
        async with AsyncLocalClient() as client:
            client._http = httpx.AsyncClient(transport=transport)
            with pytest.raises(ClientConnectionError):
                _ = [event async for event in client.invoke("Hello")]
