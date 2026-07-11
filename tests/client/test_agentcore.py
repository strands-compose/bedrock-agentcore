"""Tests for AgentCoreClient invoke and stop_session.

Uses FakeBotoClient and FakeStreamingBody from tests/fakes/transport.py
instead of MagicMock scaffolding.  Fakes are injected at the transport
seam (client._client) -- the owned boundary between our code and boto3.
"""

from __future__ import annotations

import json
from unittest.mock import patch

import pytest
from botocore.exceptions import ClientError
from strands_compose import StreamEvent

from strands_compose_agentcore.client.agentcore import AgentCoreClient, StopSessionResult
from strands_compose_agentcore.types import AccessDeniedError

from tests.fakes.transport import FakeBotoClient, FakeStreamingBody


def _make_client(fake_boto: FakeBotoClient) -> AgentCoreClient:
    """Build an AgentCoreClient with the boto3 client replaced by a fake.

    Patches boto3.Session so __init__ doesn't make real AWS calls,
    then swaps in the fake client on the instance.
    """
    with patch("boto3.Session") as mock_session_cls:
        mock_session = mock_session_cls.return_value
        mock_session.region_name = "us-east-1"
        mock_session.client.return_value = fake_boto
        client = AgentCoreClient("arn:aws:bedrock:us-east-1:123:agent-runtime/test")
    # Ensure the fake is wired (in case __init__ assigns differently)
    client._client = fake_boto
    return client


class TestAgentCoreClientInvoke:
    """AgentCoreClient.invoke yields StreamEvent from boto3 streaming response."""

    async def test_invoke_yields_stream_events(self) -> None:
        event_dict = {"type": "text", "agent_name": "agent", "data": {"text": "hi"}}
        sse_line = f"data: {json.dumps(event_dict)}"
        fake_body = FakeStreamingBody([sse_line.encode("utf-8")])
        fake_boto = FakeBotoClient(invoke_response={"response": fake_body})

        client = _make_client(fake_boto)
        session_id = "s" * 33
        events = [event async for event in client.invoke("Hello", session_id=session_id)]

        assert len(events) == 1
        assert isinstance(events[0], StreamEvent)
        assert events[0].type == "text"
        client.close()

    async def test_invoke_translates_access_denied_error(self) -> None:
        error_response = {"Error": {"Code": "AccessDeniedException", "Message": "denied"}}
        client_error = ClientError(error_response, "InvokeAgentRuntime")
        fake_boto = FakeBotoClient(invoke_error=client_error)

        client = _make_client(fake_boto)
        session_id = "s" * 33

        with pytest.raises(AccessDeniedError):
            _ = [event async for event in client.invoke("Hello", session_id=session_id)]
        client.close()

    async def test_invoke_passes_correct_payload_shape(self) -> None:
        fake_body = FakeStreamingBody([])
        fake_boto = FakeBotoClient(invoke_response={"response": fake_body})

        client = _make_client(fake_boto)
        session_id = "s" * 33
        _ = [event async for event in client.invoke("Hello world", session_id=session_id)]

        assert len(fake_boto.invoke_calls) == 1
        call = fake_boto.invoke_calls[0]
        assert call["agentRuntimeArn"] == "arn:aws:bedrock:us-east-1:123:agent-runtime/test"
        assert call["runtimeSessionId"] == session_id
        payload = json.loads(call["payload"])
        assert payload == {"prompt": "Hello world"}
        client.close()


class TestAgentCoreClientStopSession:
    """AgentCoreClient.stop_session returns StopSessionResult."""

    async def test_stop_session_returns_result(self) -> None:
        session_id = "s" * 33
        fake_boto = FakeBotoClient(
            # invoke_response needed for constructor but not used here
            invoke_response={"response": FakeStreamingBody([])},
            stop_response={
                "runtimeSessionId": session_id,
                "statusCode": 200,
            },
        )

        client = _make_client(fake_boto)
        result = await client.stop_session(session_id)

        assert isinstance(result, StopSessionResult)
        assert result.runtime_session_id == session_id
        assert result.status_code == 200
        client.close()

    async def test_stop_session_translates_access_denied(self) -> None:
        error_response = {"Error": {"Code": "AccessDeniedException", "Message": "denied"}}
        client_error = ClientError(error_response, "StopRuntimeSession")
        fake_boto = FakeBotoClient(
            invoke_response={"response": FakeStreamingBody([])},
            stop_error=client_error,
        )

        client = _make_client(fake_boto)
        session_id = "s" * 33

        with pytest.raises(AccessDeniedError):
            await client.stop_session(session_id)
        client.close()
