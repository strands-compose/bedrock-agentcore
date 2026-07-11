"""Tests for validate_session_id.

The error_event shape is pinned once in tests/contract/test_wire_shape.py, so
it is not re-tested here.
"""

from __future__ import annotations

import pytest

from strands_compose_agentcore._utils import validate_session_id


class TestValidateSessionId:
    """validate_session_id enforces the 33-256 char length window."""

    def test_validate_session_id_accepts_none(self) -> None:
        validate_session_id(None)  # must not raise

    def test_validate_session_id_accepts_min_length(self) -> None:
        validate_session_id("a" * 33)  # must not raise

    def test_validate_session_id_accepts_max_length(self) -> None:
        validate_session_id("b" * 256)  # must not raise

    def test_validate_session_id_rejects_below_min_length(self) -> None:
        with pytest.raises(ValueError):
            validate_session_id("c" * 32)

    def test_validate_session_id_rejects_above_max_length(self) -> None:
        with pytest.raises(ValueError):
            validate_session_id("d" * 257)
