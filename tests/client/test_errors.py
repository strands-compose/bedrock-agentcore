"""Tests for translate_error: maps AWS error codes to typed exceptions."""

from __future__ import annotations

import pytest

from strands_compose_agentcore.client.utils import translate_error
from strands_compose_agentcore.types import (
    AccessDeniedError,
    AgentCoreClientError,
    ConflictError,
    InvalidRequestError,
    RetryableConflictError,
    SessionNotFoundError,
    ThrottledError,
)


class _FakeClientError:
    """Simulates botocore ClientError with response metadata."""

    def __init__(self, code: str, message: str = "Something went wrong") -> None:
        self.response = {"Error": {"Code": code, "Message": message}}


@pytest.mark.parametrize(
    ("code", "expected_type"),
    [
        ("AccessDeniedException", AccessDeniedError),
        ("ThrottlingException", ThrottledError),
        ("ResourceNotFoundException", SessionNotFoundError),
        ("ValidationException", InvalidRequestError),
        ("ConflictException", ConflictError),
        ("RetryableConflictException", RetryableConflictError),
    ],
)
class TestTranslateErrorKnownCodes:
    """translate_error maps each known code to its exception subclass."""

    def test_translate_error_maps_code_to_correct_exception(
        self, code: str, expected_type: type
    ) -> None:
        exc = _FakeClientError(code)
        result = translate_error(exc)
        assert isinstance(result, expected_type)


class TestTranslateErrorUnknownCode:
    """translate_error falls back to base class for unknown codes."""

    def test_translate_error_unknown_code_returns_base_error(self) -> None:
        exc = _FakeClientError("UnknownServiceException")
        result = translate_error(exc)
        assert type(result) is AgentCoreClientError
