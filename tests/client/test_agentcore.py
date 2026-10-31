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
import io
import sys
import threading
from collections.abc import AsyncIterator, Iterator

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
from tests.fakes.transport import LiveSSEStream, sse_body, sse_line, streaming_body

_ARN = "arn:aws:bedrock-agentcore:us-east-1:0:runtime/test"
_SID = "s" * 33
# Deadlock guard only: every awaited step below completes in milliseconds.
_GUARD = 2.0
# Windows cannot wake a socket read blocked in another thread: an aborted
# stream ends only at the socket read timeout there.
_needs_read_abort = pytest.mark.skipif(
    sys.platform == "win32", reason="Windows cannot interrupt a blocked socket read"
)


def _client(
    *, retry: RetryConfig | None = None, max_concurrent_streams: int = 64
) -> AgentCoreClient:
    """Build a client without touching AWS (region supplied explicitly)."""
    return AgentCoreClient(
        _ARN, region="us-east-1", retry=retry, max_concurrent_streams=max_concurrent_streams
    )


def _stream_response(body: object) -> dict[str, object]:
    return {"response": body, "contentType": "text/event-stream"}


async def _collect(stream: AsyncIterator[StreamEvent]) -> list[StreamEvent]:
    return [e async for e in stream]


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

    async def test_slow_consumer_does_not_make_the_client_read_ahead(self) -> None:
        # The response is far larger than one read.  While the caller sits on
        # the first event, the client must not pull the rest into memory.
        client = _client()
        content = io.BytesIO(
            "".join(f"{sse_line(text='x' * 1000)}\n" for _ in range(200)).encode("utf-8")
        )
        total = len(content.getvalue())
        with Stubber(client._client) as stub:
            stub.add_response("invoke_agent_runtime", _stream_response(streaming_body(content)))
            stream = client.invoke("Hello", session_id=_SID)
            await anext(stream)
            consumed = content.tell()
            await stream.aclose()

        assert consumed < total
        client.close()


class TestAgentCoreClientConcurrency:
    """``max_concurrent_streams`` is a real cap, and a finished caller frees its slot."""

    async def test_invocation_beyond_the_cap_waits_for_a_free_slot(
        self, live: LiveSSEStream
    ) -> None:
        client = _client(max_concurrent_streams=1)
        with Stubber(client._client) as stub:
            stub.add_response("invoke_agent_runtime", _stream_response(live.body))
            first = client.invoke("A", session_id=_SID)
            live.send(sse_line("agent_start"))
            await asyncio.wait_for(anext(first), _GUARD)  # A holds the only slot
            second = asyncio.create_task(_collect(client.invoke("B", session_id=_SID)))

            # B's response is not stubbed yet: had B called AWS while A was
            # streaming, Stubber would have failed it.
            live.send(sse_line(text="a"))
            live.end()
            first_rest = [e.type async for e in first]
            stub.add_response("invoke_agent_runtime", _stream_response(sse_body(sse_line())))
            second_events = await asyncio.wait_for(second, _GUARD)

        assert first_rest == ["token"]
        assert [e.type for e in second_events] == ["token"]
        client.close()

    @_needs_read_abort
    async def test_cancelled_consumer_frees_its_slot_and_connection_at_once(
        self, live: LiveSSEStream
    ) -> None:
        # A browser that disconnects cancels the request task while the client
        # waits on a silent AWS stream.  The wait must end immediately -- not
        # at the socket read timeout -- so the next caller is not held up.
        client = _client(max_concurrent_streams=1)
        with Stubber(client._client) as stub:
            stub.add_response("invoke_agent_runtime", _stream_response(live.body))
            stub.add_response("invoke_agent_runtime", _stream_response(sse_body(sse_line())))
            first = client.invoke("A", session_id=_SID)
            live.send(sse_line("agent_start"))
            await anext(first)
            waiting = asyncio.create_task(anext(first))
            assert await asyncio.to_thread(live.wait_until_client_reads)

            # Watch from another thread: if cleanup froze the event loop until
            # the socket read timed out, the watcher gives up first.
            watcher = asyncio.create_task(asyncio.to_thread(live.client_disconnected))
            waiting.cancel()
            with pytest.raises(asyncio.CancelledError):
                await waiting
            disconnected = await watcher
            second = await asyncio.wait_for(_collect(client.invoke("B", session_id=_SID)), _GUARD)

        assert disconnected
        assert [e.type for e in second] == ["token"]
        client.close()

    async def test_consumer_cancelled_before_aws_answers_releases_the_late_response(
        self, live: LiveSSEStream
    ) -> None:
        # Cold starts make the first AWS call slow.  A caller that gives up
        # meanwhile must not leak the response AWS sends afterwards, and its
        # slot must come back for the next caller.
        aws_called, aws_answers = threading.Event(), threading.Event()

        def slow_aws(**_: object) -> None:
            aws_called.set()
            aws_answers.wait(_GUARD)

        client = _client(max_concurrent_streams=1)
        client._client.meta.events.register(
            "before-parameter-build.bedrock-agentcore.InvokeAgentRuntime", slow_aws
        )
        with Stubber(client._client) as stub:
            stub.add_response("invoke_agent_runtime", _stream_response(live.body))
            stub.add_response("invoke_agent_runtime", _stream_response(sse_body(sse_line())))
            first = asyncio.create_task(anext(client.invoke("A", session_id=_SID)))
            assert await asyncio.to_thread(aws_called.wait, _GUARD)

            first.cancel()
            with pytest.raises(asyncio.CancelledError):
                await first
            second = asyncio.create_task(_collect(client.invoke("B", session_id=_SID)))
            aws_answers.set()
            second_events = await asyncio.wait_for(second, _GUARD)
            disconnected = await asyncio.to_thread(live.client_disconnected)

        assert [e.type for e in second_events] == ["token"]
        assert disconnected
        client.close()


class TestAgentCoreClientLifecycle:
    """Closing the client aborts open streams and refuses new work."""

    @_needs_read_abort
    async def test_leaving_async_with_aborts_open_streams_and_refuses_new_work(
        self, live: LiveSSEStream
    ) -> None:
        # The FastAPI lifespan pattern: the shared client closes while a
        # request is still waiting on AWS.  Shutdown must not wait for that
        # stream, and the waiting caller must get an error, not a clean end.
        client = _client()
        with Stubber(client._client) as stub:
            stub.add_response("invoke_agent_runtime", _stream_response(live.body))
            async with client:
                stream = client.invoke("Hello", session_id=_SID)
                live.send(sse_line("agent_start"))
                await anext(stream)
                waiting = asyncio.create_task(anext(stream))
                assert await asyncio.to_thread(live.wait_until_client_reads)

            with pytest.raises(ResponseStreamingError):
                await asyncio.wait_for(waiting, _GUARD)
            with pytest.raises(RuntimeError):
                await anext(client.invoke("Hello", session_id=_SID))
            await client.aclose()  # closing again is a no-op


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

    async def test_stop_session_runs_while_every_stream_slot_is_busy(
        self, live: LiveSSEStream
    ) -> None:
        # Stopping a runaway session matters most when all streams are busy.
        client = _client(max_concurrent_streams=1)
        with Stubber(client._client) as stub:
            stub.add_response("invoke_agent_runtime", _stream_response(live.body))
            stub.add_response("stop_runtime_session", {"runtimeSessionId": _SID, "statusCode": 200})
            stream = client.invoke("Hello", session_id=_SID)
            live.send(sse_line("agent_start"))
            await anext(stream)
            waiting = asyncio.create_task(anext(stream))
            assert await asyncio.to_thread(live.wait_until_client_reads)

            result = await asyncio.wait_for(client.stop_session(_SID), _GUARD)
            live.end()
            with pytest.raises(StopAsyncIteration):
                await waiting

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
