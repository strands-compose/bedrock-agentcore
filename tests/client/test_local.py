"""Tests for LocalClient and AsyncLocalClient invoke contracts."""

from __future__ import annotations

import io
import json
from unittest.mock import MagicMock, patch

import httpx
import pytest
from strands_compose import StreamEvent

from strands_compose_agentcore.client.local import AsyncLocalClient, LocalClient
from strands_compose_agentcore.types import ClientConnectionError


class TestLocalClientInvoke:
    """LocalClient.invoke yields StreamEvent from mocked urllib response."""

    def test_local_client_invoke_yields_stream_events(self) -> None:
        event_dict = {"type": "text", "agent_name": "agent", "data": {"text": "hi"}}
        sse_line = f"data: {json.dumps(event_dict)}\n"
        fake_response = io.BytesIO(sse_line.encode("utf-8"))

        mock_ctx = MagicMock()
        mock_ctx.__enter__ = MagicMock(return_value=fake_response)
        mock_ctx.__exit__ = MagicMock(return_value=False)

        with patch("strands_compose_agentcore.client.local.urlopen", return_value=mock_ctx):
            client = LocalClient()
            events = list(client.invoke("Hello"))

        assert len(events) == 1
        assert isinstance(events[0], StreamEvent)
        assert events[0].type == "text"

    def test_local_client_invoke_raises_connection_error(self) -> None:
        from urllib.error import URLError

        with patch(
            "strands_compose_agentcore.client.local.urlopen",
            side_effect=URLError("Connection refused"),
        ):
            client = LocalClient()
            with pytest.raises(ClientConnectionError):
                list(client.invoke("Hello"))


class TestAsyncLocalClientInvoke:
    """AsyncLocalClient.invoke yields StreamEvent from mocked httpx stream."""

    async def test_async_local_client_invoke_yields_stream_events(self) -> None:
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

    async def test_async_local_client_invoke_raises_connection_error(self) -> None:
        async def mock_transport(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("refused")

        transport = httpx.MockTransport(mock_transport)
        async with AsyncLocalClient() as client:
            client._http = httpx.AsyncClient(transport=transport)
            with pytest.raises(ClientConnectionError):
                _ = [event async for event in client.invoke("Hello")]
