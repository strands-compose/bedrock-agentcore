"""Tests for build_invocation_body: string, dict, list, and error cases."""

from __future__ import annotations

import pytest

from strands_compose_agentcore.client.utils import build_invocation_body


class TestBuildInvocationBody:
    """build_invocation_body transforms agent inputs into wire format."""

    def test_body_wraps_string_input_as_prompt(self) -> None:
        result = build_invocation_body("Hello agent")
        assert result == {"prompt": "Hello agent"}

    def test_body_wraps_single_dict_block_in_list(self) -> None:
        block = {"text": "hello"}
        result = build_invocation_body(block)  # ty: ignore[invalid-argument-type]
        assert result == {"prompt": [{"text": "hello"}]}

    def test_body_preserves_non_empty_list_of_blocks(self) -> None:
        blocks = [{"text": "a"}, {"text": "b"}]
        result = build_invocation_body(blocks)  # ty: ignore[invalid-argument-type]
        assert result == {"prompt": [{"text": "a"}, {"text": "b"}]}

    def test_body_raises_value_error_for_empty_list(self) -> None:
        with pytest.raises(ValueError, match="invalid"):
            build_invocation_body([])

    def test_body_raises_value_error_for_unsupported_type(self) -> None:
        with pytest.raises(ValueError, match="invalid"):
            build_invocation_body(42)  # ty: ignore[invalid-argument-type]
