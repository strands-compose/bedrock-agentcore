"""Tests for AgentCoreClient invoke and stop_session."""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest
from strands_compose import StreamEvent

from strands_compose_agentcore.client.agentcore import AgentCoreClient, StopSessionResult
from strands_compose_agentcore.types import AccessDeniedError


class _FakeStreamingBody:
    """Simulates botocore StreamingBody for SSE line iteration."""

    def __init__(self, lines: list[bytes]) -> None:
        self._lines = lines

    def iter_lines(self):
        return iter(self._lines)

    def close(self):
        pass


class TestAgentCoreClientInvoke:
    """AgentCoreClient.invoke yields StreamEvent from mocked boto3 response."""

    async def test_agentcore_client_invoke_yields_stream_events(self) -> None:
        event_dict = {"type": "text", "agent_name": "agent", "data": {"text": "hi"}}
        sse_line = f"data: {json.dumps(event_dict)}"
        fake_body = _FakeStreamingBody([sse_line.encode("utf-8")])

        with patch("boto3.Session") as mock_session_cls:
            mock_session = MagicMock()
            mock_session.region_name = "us-east-1"
            mock_client = MagicMock()
            mock_client.invoke_agent_runtime.return_value = {"response": fake_body}
            mock_session.client.return_value = mock_client
            mock_session_cls.return_value = mock_session

            client = AgentCoreClient("arn:aws:bedrock:us-east-1:123:agent-runtime/test")
            client._client = mock_client

            session_id = "s" * 33
            events = [event async for event in client.invoke("Hello", session_id=session_id)]

        assert len(events) == 1
        assert isinstance(events[0], StreamEvent)
        assert events[0].type == "text"
        client.close()

    async def test_agentcore_client_invoke_translates_access_denied(self) -> None:
        from botocore.exceptions import ClientError

        error_response = {"Error": {"Code": "AccessDeniedException", "Message": "denied"}}

        with patch("boto3.Session") as mock_session_cls:
            mock_session = MagicMock()
            mock_session.region_name = "us-east-1"
            mock_client = MagicMock()
            mock_client.invoke_agent_runtime.side_effect = ClientError(
                error_response, "InvokeAgentRuntime"
            )
            mock_session.client.return_value = mock_client
            mock_session_cls.return_value = mock_session

            client = AgentCoreClient("arn:aws:bedrock:us-east-1:123:agent-runtime/test")
            client._client = mock_client

            session_id = "s" * 33
            with pytest.raises(AccessDeniedError):
                _ = [event async for event in client.invoke("Hello", session_id=session_id)]
            client.close()


class TestAgentCoreClientStopSession:
    """AgentCoreClient.stop_session returns StopSessionResult."""

    async def test_stop_session_returns_result(self) -> None:
        with patch("boto3.Session") as mock_session_cls:
            mock_session = MagicMock()
            mock_session.region_name = "us-east-1"
            mock_client = MagicMock()
            mock_client.stop_runtime_session.return_value = {
                "runtimeSessionId": "s" * 33,
                "statusCode": 200,
            }
            mock_session.client.return_value = mock_client
            mock_session_cls.return_value = mock_session

            client = AgentCoreClient("arn:aws:bedrock:us-east-1:123:agent-runtime/test")
            client._client = mock_client

            session_id = "s" * 33
            result = await client.stop_session(session_id)

        assert isinstance(result, StopSessionResult)
        assert result.runtime_session_id == "s" * 33
        assert result.status_code == 200
        client.close()
