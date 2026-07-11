"""Tests for AgentCoreClient invoke, stop_session, and throttle retry.

boto3 is driven through ``botocore.Stubber``, the vendor's own test seam.
Stubber validates the request against the real service model, so a wrong
parameter name fails loudly -- a fidelity a hand-rolled client fake cannot
give.  The streaming response uses a real ``botocore.response.StreamingBody``
so the client's ``iter_lines()`` path runs for real.
"""

from __future__ import annotations

import io
import json
from unittest.mock import patch

import pytest
from botocore.response import StreamingBody
from botocore.stub import Stubber
from strands_compose import StreamEvent

from strands_compose_agentcore.client.agentcore import AgentCoreClient, StopSessionResult
from strands_compose_agentcore.types import AccessDeniedError, RetryConfig, ThrottledError

_ARN = "arn:aws:bedrock-agentcore:us-east-1:0:runtime/test"
_SID = "s" * 33


def _client(*, retry: RetryConfig | None = None) -> AgentCoreClient:
    """Build a client without touching AWS (region supplied explicitly)."""
    return AgentCoreClient(_ARN, region="us-east-1", retry=retry)


def _streaming_body(*sse_lines: str) -> StreamingBody:
    """Wrap SSE lines in a real StreamingBody, as boto3 would return."""
    raw = "".join(f"{line}\n" for line in sse_lines).encode("utf-8")
    return StreamingBody(io.BytesIO(raw), len(raw))


class TestAgentCoreClientInvoke:
    """AgentCoreClient.invoke streams StreamEvents and validates the request."""

    async def test_invoke_yields_stream_events_and_sends_correct_request(self) -> None:
        client = _client()
        event = {"type": "token", "agent_name": "a", "data": {"text": "hi"}}
        with Stubber(client._client) as stub:
            stub.add_response(
                "invoke_agent_runtime",
                {
                    "response": _streaming_body(f"data: {json.dumps(event)}"),
                    "contentType": "text/event-stream",
                },
                expected_params={
                    "agentRuntimeArn": _ARN,
                    "payload": b'{"prompt": "Hello world"}',
                    "contentType": "application/json",
                    "accept": "text/event-stream",
                    "runtimeSessionId": _SID,
                },
            )
            events = [e async for e in client.invoke("Hello world", session_id=_SID)]

        assert [e.type for e in events] == ["token"]
        assert isinstance(events[0], StreamEvent)
        client.close()

    async def test_invoke_translates_access_denied_error(self) -> None:
        client = _client()
        with Stubber(client._client) as stub:
            stub.add_client_error(
                "invoke_agent_runtime", service_error_code="AccessDeniedException"
            )
            with pytest.raises(AccessDeniedError):
                _ = [e async for e in client.invoke("Hello", session_id=_SID)]
        client.close()

    async def test_invoke_retries_throttling_then_raises_throttled_error(self) -> None:
        client = _client(retry=RetryConfig(max_retries=2, base_delay=0.01, jitter=False))
        with Stubber(client._client) as stub:
            for _ in range(3):  # initial attempt + 2 retries all throttled
                stub.add_client_error(
                    "invoke_agent_runtime", service_error_code="ThrottlingException"
                )
            with patch("strands_compose_agentcore.client.agentcore.asyncio.sleep") as mock_sleep:
                mock_sleep.return_value = None
                with pytest.raises(ThrottledError):
                    _ = [e async for e in client.invoke("Hello", session_id=_SID)]
        client.close()


class TestAgentCoreClientStopSession:
    """AgentCoreClient.stop_session returns StopSessionResult or a typed error."""

    async def test_stop_session_returns_result(self) -> None:
        client = _client()
        with Stubber(client._client) as stub:
            stub.add_response(
                "stop_runtime_session",
                {"runtimeSessionId": _SID, "statusCode": 200},
                expected_params={"agentRuntimeArn": _ARN, "runtimeSessionId": _SID},
            )
            result = await client.stop_session(_SID)

        assert isinstance(result, StopSessionResult)
        assert result.runtime_session_id == _SID
        assert result.status_code == 200
        client.close()

    async def test_stop_session_translates_access_denied(self) -> None:
        client = _client()
        with Stubber(client._client) as stub:
            stub.add_client_error(
                "stop_runtime_session", service_error_code="AccessDeniedException"
            )
            with pytest.raises(AccessDeniedError):
                await client.stop_session(_SID)
        client.close()
