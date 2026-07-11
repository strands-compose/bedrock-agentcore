"""Hand-written fakes for transport seams (boto3, urllib, botocore).

These replace the per-file _FakeStreamingBody / _FakeClientError inlines
and the MagicMock scaffolding in client tests.  Each fake is a real object
with working behaviour that survives dependency upgrades.
"""

from __future__ import annotations

from typing import Any


class FakeStreamingBody:
    """Simulates botocore StreamingBody for SSE line iteration.

    Provides iter_lines() and close() -- the only two methods our
    adapter touches on a real StreamingBody.
    """

    def __init__(self, lines: list[bytes]) -> None:
        self._lines = lines
        self.closed = False

    def iter_lines(self):
        """Yield pre-loaded lines one at a time."""
        return iter(self._lines)

    def close(self):
        """Mark as closed."""
        self.closed = True


class FakeBotoClient:
    """Stands in for the boto3 bedrock-agentcore service client.

    Provides invoke_agent_runtime() and stop_runtime_session() with
    configurable responses or errors.  No real AWS calls, no MagicMock.
    """

    def __init__(
        self,
        *,
        invoke_response: dict[str, Any] | None = None,
        invoke_error: Exception | None = None,
        stop_response: dict[str, Any] | None = None,
        stop_error: Exception | None = None,
    ) -> None:
        self._invoke_response = invoke_response
        self._invoke_error = invoke_error
        self._stop_response = stop_response
        self._stop_error = stop_error
        self.invoke_calls: list[dict[str, Any]] = []
        self.stop_calls: list[dict[str, Any]] = []

    def invoke_agent_runtime(self, **kwargs: Any) -> dict[str, Any]:
        """Record the call and return canned response or raise."""
        self.invoke_calls.append(kwargs)
        if self._invoke_error:
            raise self._invoke_error
        assert self._invoke_response is not None
        return self._invoke_response

    def stop_runtime_session(self, **kwargs: Any) -> dict[str, Any]:
        """Record the call and return canned response or raise."""
        self.stop_calls.append(kwargs)
        if self._stop_error:
            raise self._stop_error
        assert self._stop_response is not None
        return self._stop_response


class FakeClientError(Exception):
    """Minimal botocore.exceptions.ClientError stand-in for import-free use.

    For tests that need to construct a real ClientError, import from botocore.
    This fake is for tests that only need to verify translate_error behaviour
    without importing botocore at the test level.
    """

    def __init__(self, code: str, message: str = "error") -> None:
        self.response = {"Error": {"Code": code, "Message": message}}
        self.operation_name = "TestOperation"
        super().__init__(f"{code}: {message}")


class FakeUrlResponse:
    """Stands in for the urllib response context manager.

    Provides iteration over pre-loaded byte lines -- the only protocol
    our LocalClient uses on the urlopen return value.
    """

    def __init__(self, lines: list[bytes]) -> None:
        self._lines = lines

    def __enter__(self):
        return self

    def __exit__(self, *exc: object):
        pass

    def __iter__(self):
        return iter(self._lines)
