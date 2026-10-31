"""Tests for AgentCoreClient invoke, stop_session, and throttle retry.

boto3 is driven through ``botocore.Stubber``, the vendor's own test seam.
Stubber validates the request against the real service model, so a wrong
parameter name fails loudly -- a fidelity a hand-rolled client fake cannot
give.  Each streaming response is a real ``StreamingBody`` over a real
``urllib3.HTTPResponse`` (see ``tests.fakes.transport``), so the client reads
through the same stack it uses against AWS.
"""

from __future__ import annotations

import asyncio
from collections.abc import Iterator

import pytest
from botocore.exceptions import ResponseStreamingError
from botocore.stub import Stubber
from strands_compose import StreamEvent

from strands_compose_agentcore.client.agentcore import AgentCoreClient, StopSessionResult
from strands_compose_agentcore.types import (
    AccessDeniedError,
    RetryableConflictError,
    RetryConfig,
    ThrottledError,
)
from tests.fakes.transport import LiveSSEStream, sse_body, sse_line

_ARN = "arn:aws:bedrock-agentcore:us-east-1:0:runtime/test"
_SID = "s" * 33
# Deadlock guard only: every awaited step below completes in milliseconds.
_GUARD = 2.0


def _client(*, retry: RetryConfig | None = None) -> AgentCoreClient:
    """Build a client without touching AWS (region supplied explicitly)."""
    return AgentCoreClient(_ARN, region="us-east-1", retry=retry)


def _stream_response(body: object) -> dict[str, object]:
    return {"response": body, "contentType": "text/event-stream"}


@pytest.fixture
def live() -> Iterator[LiveSSEStream]:
    stream = LiveSSEStream()
    yield stream
    stream.close()


class TestAgentCoreClientInvoke:
    """AgentCoreClient.invoke streams StreamEvents and validates the request."""

    async def test_invoke_yields_stream_events_and_sends_correct_request(self) -> None:
        client = _client()
        with Stubber(client._client) as stub:
            stub.add_response(
                "invoke_agent_runtime",
                _stream_response(sse_body(sse_line(text="hi"))),
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

    async def test_invoke_raw_output_yields_lines_and_filters_noise(self) -> None:
        client = _client()
        line = sse_line(text="hi")
        with Stubber(client._client) as stub:
            stub.add_response(
                "invoke_agent_runtime", _stream_response(sse_body(line, "", ": keepalive"))
            )
            lines = [x async for x in client.invoke("Hello", session_id=_SID, raw_output=True)]

        assert lines == [line, ": keepalive"]  # blanks dropped, comments passed through
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

    @pytest.mark.parametrize(
        ("error_code", "expected"),
        [
            ("ThrottlingException", ThrottledError),
            ("RetryableConflictException", RetryableConflictError),
        ],
    )
    async def test_invoke_retries_then_raises_the_typed_error(
        self, error_code: str, expected: type[Exception]
    ) -> None:
        # base_delay=0 keeps the retry deterministic without patching sleep.
        client = _client(retry=RetryConfig(max_retries=2, base_delay=0, jitter=False))
        with Stubber(client._client) as stub:
            for _ in range(3):  # initial attempt + 2 retries all fail
                stub.add_client_error("invoke_agent_runtime", service_error_code=error_code)
            with pytest.raises(expected):
                _ = [e async for e in client.invoke("Hello", session_id=_SID)]
        client.close()


class TestAgentCoreClientStreaming:
    """Events reach the caller as they arrive, and transport failures surface."""

    async def test_each_event_is_delivered_before_the_next_one_arrives(
        self, live: LiveSSEStream
    ) -> None:
        # AgentCore sends one event per HTTP chunk.  The first event must reach
        # the caller while the response is still open and silent -- a reader
        # that waits for a full buffer would block here until the socket
        # timeout.
        client = _client()
        with Stubber(client._client) as stub:
            stub.add_response("invoke_agent_runtime", _stream_response(live.body))
            stream = client.invoke("Hello", session_id=_SID)
            live.send(sse_line("agent_start"))
            first = await asyncio.wait_for(anext(stream), _GUARD)
            live.send(sse_line(text="hi"))
            second = await asyncio.wait_for(anext(stream), _GUARD)
            live.end()
            rest = [e async for e in stream]

        assert [first.type, second.type, rest] == ["agent_start", "token", []]
        client.close()

    async def test_invoke_raises_when_the_stream_dies_mid_response(
        self, live: LiveSSEStream
    ) -> None:
        # A dropped connection must not look like a clean end of stream, and
        # events received before the failure are still delivered.
        client = _client()
        received: list[str] = []
        with Stubber(client._client) as stub:
            stub.add_response("invoke_agent_runtime", _stream_response(live.body))
            live.send(sse_line(text="hi"))
            live.drop()
            with pytest.raises(ResponseStreamingError):
                async for event in client.invoke("Hello", session_id=_SID):
                    received.append(event.type)

        assert received == ["token"]
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


class TestAgentCoreClientUserId:
    """``user_id`` travels in the payload next to ``prompt``."""

    async def test_invoke_sends_user_id_in_payload(self) -> None:
        client = _client()
        with Stubber(client._client) as stub:
            stub.add_response(
                "invoke_agent_runtime",
                _stream_response(sse_body()),
                expected_params={
                    "agentRuntimeArn": _ARN,
                    "payload": b'{"prompt": "Hello", "user_id": "alice"}',
                    "contentType": "application/json",
                    "accept": "text/event-stream",
                    "runtimeSessionId": _SID,
                },
            )
            _ = [e async for e in client.invoke("Hello", session_id=_SID, user_id="alice")]
            stub.assert_no_pending_responses()
        client.close()
