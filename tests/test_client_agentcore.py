"""Tests for AgentCoreClient core behavior (init, invoke, helpers, errors)."""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import MagicMock

import pytest
from botocore.exceptions import ClientError
from strands_compose import StreamEvent

from strands_compose_agentcore.client.agentcore import (
    _STREAM_DONE,
    AgentCoreClient,
)
from strands_compose_agentcore.client.utils import (
    AccessDeniedError,
    AgentCoreClientError,
    ThrottledError,
    translate_error,
)

_TEST_ARN = "arn:aws:bedrock-agentcore:us-west-2:123456789012:runtime/test-agent"
_VALID_SESSION_ID = "a" * 33  # meets AgentCore 33-char minimum


def _make_streaming_body(lines: list[str]) -> MagicMock:
    body = MagicMock()
    body.iter_lines.return_value = iter(line.encode() for line in lines)
    return body


def _make_client_error(code: str, message: str = "test error") -> ClientError:
    return ClientError(
        {"Error": {"Code": code, "Message": message}},
        "InvokeAgentRuntime",
    )


def _make_sse_line(event_type: str, agent_name: str, data: dict[str, Any] | None = None) -> str:
    event = StreamEvent(type=event_type, agent_name=agent_name, data=data or {})
    return f"data: {json.dumps(event.asdict())}\n\n"


@pytest.fixture()
def mock_boto3_session() -> MagicMock:
    session = MagicMock()
    session.region_name = "us-west-2"
    session.client.return_value = MagicMock()
    return session


@pytest.fixture()
def client(mock_boto3_session: MagicMock) -> AgentCoreClient:
    return AgentCoreClient(_TEST_ARN, session=mock_boto3_session)


class TestAgentCoreClientInit:
    def test_init_with_explicit_region(self, mock_boto3_session: MagicMock) -> None:
        c = AgentCoreClient(_TEST_ARN, session=mock_boto3_session, region="eu-west-1")
        mock_boto3_session.client.assert_called_once()
        call_kwargs = mock_boto3_session.client.call_args
        region = call_kwargs.kwargs.get("region_name") or call_kwargs[1].get("region_name")
        assert region == "eu-west-1"
        assert c.agent_runtime_arn == _TEST_ARN

    def test_init_with_session_region(self, mock_boto3_session: MagicMock) -> None:
        mock_boto3_session.region_name = "us-east-1"
        AgentCoreClient(_TEST_ARN, session=mock_boto3_session)
        call_kwargs = mock_boto3_session.client.call_args
        region = call_kwargs.kwargs.get("region_name") or call_kwargs[1].get("region_name")
        assert region == "us-east-1"

    def test_init_missing_region_raises_value_error(self) -> None:
        session = MagicMock()
        session.region_name = None
        with pytest.raises(ValueError, match="No AWS region"):
            AgentCoreClient(_TEST_ARN, session=session)

    def test_init_stores_arn(self, client: AgentCoreClient) -> None:
        assert client.agent_runtime_arn == _TEST_ARN

    def test_init_with_timeout(self, mock_boto3_session: MagicMock) -> None:
        AgentCoreClient(_TEST_ARN, session=mock_boto3_session, timeout=120.0)
        call_kwargs = mock_boto3_session.client.call_args
        config = call_kwargs.kwargs.get("config") or call_kwargs[1].get("config")
        assert config is not None
        assert config.read_timeout == 120

    def test_init_creates_executor_with_default_workers(self, client: AgentCoreClient) -> None:
        assert client._executor._max_workers == 64

    def test_init_creates_executor_with_custom_workers(self, mock_boto3_session: MagicMock) -> None:
        c = AgentCoreClient(_TEST_ARN, session=mock_boto3_session, max_concurrent_streams=128)
        assert c._executor._max_workers == 128

    def test_close_shuts_down_executor(self, client: AgentCoreClient) -> None:
        client.close()
        assert client._executor._shutdown

    @pytest.mark.asyncio
    async def test_async_context_manager(self, mock_boto3_session: MagicMock) -> None:
        async with AgentCoreClient(_TEST_ARN, session=mock_boto3_session) as c:
            assert isinstance(c, AgentCoreClient)
        assert c._executor._shutdown


class TestInvokeSync:
    def test_invoke_sync_payload_shape(self, client: AgentCoreClient) -> None:
        mock_api = client._client.invoke_agent_runtime
        mock_api.return_value = {"response": MagicMock(), "statusCode": 200}

        client._invoke_sync("session-123", "Hello agent", None)

        mock_api.assert_called_once_with(
            agentRuntimeArn=_TEST_ARN,
            payload=json.dumps({"prompt": "Hello agent"}).encode(),
            contentType="application/json",
            accept="text/event-stream",
            runtimeSessionId="session-123",
        )

    def test_invoke_sync_payload_extras(self, client: AgentCoreClient) -> None:
        mock_api = client._client.invoke_agent_runtime
        mock_api.return_value = {"response": MagicMock(), "statusCode": 200}

        client._invoke_sync("s", "Hi", {"media": {"type": "image"}})

        call_kwargs = mock_api.call_args.kwargs
        sent_payload = json.loads(call_kwargs["payload"])
        assert sent_payload == {"prompt": "Hi", "media": {"type": "image"}}

    def test_invoke_sync_returns_response(self, client: AgentCoreClient) -> None:
        expected = {"response": MagicMock(), "statusCode": 200}
        client._client.invoke_agent_runtime.return_value = expected
        result = client._invoke_sync("s", "Hi", None)
        assert result is expected

    def test_invoke_sync_translates_client_error(self, client: AgentCoreClient) -> None:
        client._client.invoke_agent_runtime.side_effect = _make_client_error(
            "ThrottlingException", "Rate exceeded"
        )
        with pytest.raises(ThrottledError, match="Rate exceeded"):
            client._invoke_sync("s", "Hi", None)


class TestInvoke:
    @pytest.mark.asyncio
    async def test_invoke_happy_path_yields_stream_events(self, client: AgentCoreClient) -> None:
        lines = [
            _make_sse_line("agent_start", "my_agent"),
            _make_sse_line("token", "my_agent", {"text": "Hello"}),
            _make_sse_line("complete", "my_agent", {"usage": {}}),
        ]
        body = _make_streaming_body(lines)
        client._client.invoke_agent_runtime.return_value = {"response": body}

        events = [e async for e in client.invoke(session_id=_VALID_SESSION_ID, prompt="Hi")]

        assert len(events) == 3
        assert events[0].type == "agent_start"
        assert events[1].type == "token"
        assert events[1].data == {"text": "Hello"}
        assert events[2].type == "complete"

    @pytest.mark.asyncio
    async def test_invoke_rejects_short_session_id(self, client: AgentCoreClient) -> None:
        with pytest.raises(ValueError, match="too short"):
            async for _ in client.invoke(session_id="short", prompt="Hi"):
                pass  # pragma: no cover

    @pytest.mark.asyncio
    async def test_invoke_rejects_long_session_id(self, client: AgentCoreClient) -> None:
        long_id = "a" * 257
        with pytest.raises(ValueError, match="too long"):
            async for _ in client.invoke(session_id=long_id, prompt="Hi"):
                pass  # pragma: no cover

    @pytest.mark.asyncio
    async def test_invoke_skips_empty_lines(self, client: AgentCoreClient) -> None:
        lines = [
            "",
            "  ",
            _make_sse_line("token", "a", {"text": "ok"}),
            "",
        ]
        body = _make_streaming_body(lines)
        client._client.invoke_agent_runtime.return_value = {"response": body}

        events = [e async for e in client.invoke(session_id=_VALID_SESSION_ID, prompt="Hi")]
        assert len(events) == 1
        assert events[0].type == "token"

    @pytest.mark.asyncio
    async def test_invoke_skips_non_json_lines(self, client: AgentCoreClient) -> None:
        lines = [
            ":keepalive\n",
            "invalid-json\n",
            _make_sse_line("token", "a", {"text": "ok"}),
        ]
        body = _make_streaming_body(lines)
        client._client.invoke_agent_runtime.return_value = {"response": body}

        events = [e async for e in client.invoke(session_id=_VALID_SESSION_ID, prompt="Hi")]
        assert len(events) == 1

    @pytest.mark.asyncio
    async def test_invoke_handles_raw_json_without_sse_prefix(
        self, client: AgentCoreClient
    ) -> None:
        event = StreamEvent(type="token", agent_name="a", data={"text": "raw"})
        raw_line = json.dumps(event.asdict()) + "\n"
        body = _make_streaming_body([raw_line])
        client._client.invoke_agent_runtime.return_value = {"response": body}

        events = [e async for e in client.invoke(session_id=_VALID_SESSION_ID, prompt="Hi")]
        assert len(events) == 1
        assert events[0].data == {"text": "raw"}

    @pytest.mark.asyncio
    async def test_invoke_access_denied_raises_error(self, client: AgentCoreClient) -> None:
        client._client.invoke_agent_runtime.side_effect = _make_client_error(
            "AccessDeniedException"
        )
        with pytest.raises(AccessDeniedError):
            async for _ in client.invoke(session_id=_VALID_SESSION_ID, prompt="Hi"):
                pass

    @pytest.mark.asyncio
    async def test_invoke_throttling_raises_error(self, client: AgentCoreClient) -> None:
        client._client.invoke_agent_runtime.side_effect = _make_client_error("ThrottlingException")
        with pytest.raises(ThrottledError):
            async for _ in client.invoke(session_id=_VALID_SESSION_ID, prompt="Hi"):
                pass

    @pytest.mark.asyncio
    async def test_invoke_unexpected_error_wraps_in_base(self, client: AgentCoreClient) -> None:
        client._client.invoke_agent_runtime.side_effect = RuntimeError("boom")
        with pytest.raises(AgentCoreClientError, match="boom"):
            async for _ in client.invoke(session_id=_VALID_SESSION_ID, prompt="Hi"):
                pass

    @pytest.mark.asyncio
    async def test_invoke_payload_extras_forwarded(self, client: AgentCoreClient) -> None:
        body = _make_streaming_body([_make_sse_line("complete", "a")])
        client._client.invoke_agent_runtime.return_value = {"response": body}

        extras = {"media": {"type": "image", "data": "abc"}}
        _ = [
            e
            async for e in client.invoke(
                session_id=_VALID_SESSION_ID, prompt="Hi", payload_extras=extras
            )
        ]

        call_kwargs = client._client.invoke_agent_runtime.call_args.kwargs
        sent_payload = json.loads(call_kwargs["payload"])
        assert sent_payload["media"] == {"type": "image", "data": "abc"}
        assert sent_payload["prompt"] == "Hi"


class TestTranslateError:
    def test_translate_access_denied(self) -> None:
        err = _make_client_error("AccessDeniedException", "no perms")
        result = translate_error(err)
        assert isinstance(result, AccessDeniedError)

    def test_translate_throttling(self) -> None:
        err = _make_client_error("ThrottlingException", "rate limited")
        result = translate_error(err)
        assert isinstance(result, ThrottledError)

    def test_translate_unknown_code_returns_base(self) -> None:
        err = _make_client_error("ResourceNotFoundException", "not found")
        result = translate_error(err)
        assert isinstance(result, AgentCoreClientError)
        assert not isinstance(result, (AccessDeniedError, ThrottledError))
        assert "ResourceNotFoundException" in str(result)

    def test_translate_preserves_message(self) -> None:
        err = _make_client_error("ValidationException", "specific reason")
        result = translate_error(err)
        assert "specific reason" in str(result)

    def test_translate_includes_error_code_in_message(self) -> None:
        err = _make_client_error("ValidationException", "bad payload")
        result = translate_error(err)
        assert "[ValidationException]" in str(result)


class TestNextLine:
    def test_next_line_returns_bytes(self) -> None:
        result = AgentCoreClient._next_line(iter([b"hello"]))
        assert result == b"hello"

    def test_next_line_returns_sentinel_on_exhaustion(self) -> None:
        result = AgentCoreClient._next_line(iter([]))
        assert result is _STREAM_DONE


class TestInvokeRetry:
    @pytest.mark.asyncio
    async def test_retries_on_throttling(self, mock_boto3_session: MagicMock) -> None:
        from strands_compose_agentcore.client.utils import RetryConfig

        client = AgentCoreClient(
            _TEST_ARN,
            session=mock_boto3_session,
            retry=RetryConfig(max_retries=2, base_delay=0.01, jitter=False),
        )
        body = _make_streaming_body([_make_sse_line("complete", "a")])

        client._client.invoke_agent_runtime.side_effect = [
            _make_client_error("ThrottlingException"),
            _make_client_error("ThrottlingException"),
            {"response": body},
        ]
        events = [e async for e in client.invoke(session_id=_VALID_SESSION_ID, prompt="Hi")]
        assert len(events) == 1
        assert client._client.invoke_agent_runtime.call_count == 3

    @pytest.mark.asyncio
    async def test_raises_after_max_retries(self, mock_boto3_session: MagicMock) -> None:
        from strands_compose_agentcore.client.utils import RetryConfig

        client = AgentCoreClient(
            _TEST_ARN,
            session=mock_boto3_session,
            retry=RetryConfig(max_retries=1, base_delay=0.01, jitter=False),
        )
        client._client.invoke_agent_runtime.side_effect = _make_client_error("ThrottlingException")
        with pytest.raises(ThrottledError):
            async for _ in client.invoke(session_id=_VALID_SESSION_ID, prompt="Hi"):
                pass

    @pytest.mark.asyncio
    async def test_no_retry_on_access_denied(self, mock_boto3_session: MagicMock) -> None:
        from strands_compose_agentcore.client.utils import RetryConfig

        client = AgentCoreClient(
            _TEST_ARN,
            session=mock_boto3_session,
            retry=RetryConfig(max_retries=3, base_delay=0.01),
        )
        client._client.invoke_agent_runtime.side_effect = _make_client_error(
            "AccessDeniedException"
        )
        with pytest.raises(AccessDeniedError):
            async for _ in client.invoke(session_id=_VALID_SESSION_ID, prompt="Hi"):
                pass
        assert client._client.invoke_agent_runtime.call_count == 1

    @pytest.mark.asyncio
    async def test_no_retry_by_default(self, mock_boto3_session: MagicMock) -> None:
        client = AgentCoreClient(_TEST_ARN, session=mock_boto3_session)
        client._client.invoke_agent_runtime.side_effect = _make_client_error("ThrottlingException")
        with pytest.raises(ThrottledError):
            async for _ in client.invoke(session_id=_VALID_SESSION_ID, prompt="Hi"):
                pass
        assert client._client.invoke_agent_runtime.call_count == 1
