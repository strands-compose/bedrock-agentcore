"""Tests for the multimodal payload parser."""

from __future__ import annotations

import base64
from typing import Any

import pytest

from strands_compose_agentcore.payload import (
    MultimodalPayloadError,
    parse_payload,
)

_LIMITS: dict[str, Any] = {
    "max_payload_bytes": 1024 * 1024,
    "max_media_bytes": 1024 * 1024,
    "max_media_blocks": 5,
}


def _b64(data: bytes) -> str:
    return base64.b64encode(data).decode("ascii")


def _parse(payload: Any, **overrides: Any) -> Any:
    kwargs = {**_LIMITS, **overrides}
    return parse_payload(payload, **kwargs)


class TestParsePromptShape:
    def test_returns_prompt_string(self) -> None:
        result = parse_payload({"prompt": "hi"}, **_LIMITS)
        assert result == "hi"

    def test_rejects_empty_prompt(self) -> None:
        with pytest.raises(MultimodalPayloadError, match="empty"):
            parse_payload({"prompt": ""}, **_LIMITS)

    def test_rejects_non_supported_prompt(self) -> None:
        with pytest.raises(MultimodalPayloadError, match="must be a string"):
            parse_payload({"prompt": 42}, **_LIMITS)


class TestParseShape:
    def test_rejects_missing_prompt(self) -> None:
        with pytest.raises(MultimodalPayloadError, match="missing required field"):
            parse_payload({}, **_LIMITS)

    def test_rejects_messages_shape(self) -> None:
        with pytest.raises(MultimodalPayloadError, match="missing required field"):
            parse_payload({"messages": [{"role": "user", "content": [{"text": "x"}]}]}, **_LIMITS)

    def test_rejects_non_mapping(self) -> None:
        with pytest.raises(MultimodalPayloadError, match="must be a JSON object"):
            parse_payload("hi", **_LIMITS)  # ty: ignore[invalid-argument-type]

    def test_ignores_unknown_top_level_keys(self) -> None:
        result = parse_payload({"prompt": "hi", "extra": 1}, **_LIMITS)
        assert result == "hi"


class TestParseBlocks:
    def test_list_of_blocks_passes_through(self) -> None:
        result = parse_payload({"prompt": [{"text": "describe"}]}, **_LIMITS)
        assert result == [{"text": "describe"}]

    def test_single_block_dict_is_wrapped(self) -> None:
        result = parse_payload({"prompt": {"text": "describe"}}, **_LIMITS)
        assert result == [{"text": "describe"}]

    def test_rejects_empty_block_list(self) -> None:
        with pytest.raises(MultimodalPayloadError, match="must not be empty"):
            parse_payload({"prompt": []}, **_LIMITS)

    def test_rejects_non_dict_block(self) -> None:
        with pytest.raises(MultimodalPayloadError, match="JSON object"):
            parse_payload({"prompt": ["not-a-block"]}, **_LIMITS)

    def test_rejects_unknown_block_type(self) -> None:
        with pytest.raises(MultimodalPayloadError, match="exactly one"):
            parse_payload({"prompt": [{"video": {"format": "mp4"}}]}, **_LIMITS)

    def test_rejects_multiple_block_types(self) -> None:
        with pytest.raises(MultimodalPayloadError, match="exactly one"):
            parse_payload({"prompt": [{"text": "x", "image": {}}]}, **_LIMITS)


class TestMediaDecoding:
    def test_image_base64_decoded_to_bytes(self) -> None:
        raw = b"\x89PNG\r\n"
        payload = {"prompt": [{"image": {"format": "png", "source": {"base64": _b64(raw)}}}]}
        result = _parse(payload)
        assert result[0]["image"]["source"] == {"bytes": raw}

    def test_document_base64_decoded_to_bytes(self) -> None:
        raw = b"%PDF-1.4"
        payload = {
            "prompt": [
                {
                    "document": {
                        "format": "pdf",
                        "name": "x.pdf",
                        "source": {"base64": _b64(raw)},
                    }
                }
            ]
        }
        result = _parse(payload)
        assert result[0]["document"]["source"] == {"bytes": raw}

    def test_rejects_s3_location_source(self) -> None:
        payload = {
            "prompt": [
                {
                    "image": {
                        "format": "png",
                        "source": {"location": {"type": "s3", "uri": "s3://bucket/key.png"}},
                    }
                }
            ]
        }
        with pytest.raises(MultimodalPayloadError, match="base64"):
            parse_payload(payload, **_LIMITS)

    def test_rejects_non_string_base64(self) -> None:
        payload = {"prompt": [{"image": {"format": "png", "source": {"base64": 1}}}]}
        with pytest.raises(MultimodalPayloadError, match="must be a string"):
            parse_payload(payload, **_LIMITS)

    def test_rejects_malformed_base64(self) -> None:
        payload = {"prompt": [{"image": {"format": "png", "source": {"base64": "!!!"}}}]}
        with pytest.raises(MultimodalPayloadError, match="valid base64"):
            parse_payload(payload, **_LIMITS)

    def test_rejects_unsupported_image_format(self) -> None:
        payload = {"prompt": [{"image": {"format": "pdf", "source": {"base64": "AAA="}}}]}
        with pytest.raises(MultimodalPayloadError, match="not supported"):
            parse_payload(payload, **_LIMITS)

    def test_rejects_missing_document_name(self) -> None:
        payload = {"prompt": [{"document": {"format": "pdf", "source": {"base64": "AAA="}}}]}
        with pytest.raises(MultimodalPayloadError, match="exactly"):
            parse_payload(payload, **_LIMITS)


class TestReplyDecoding:
    def test_reply_converts_to_interrupt_response(self) -> None:
        payload = {"prompt": [{"reply": {"interrupt_id": "iid", "response": "yes"}}]}
        assert _parse(payload) == [{"interruptResponse": {"interruptId": "iid", "response": "yes"}}]

    def test_rejects_reply_mixed_with_text(self) -> None:
        payload = {
            "prompt": [
                {"reply": {"interrupt_id": "iid", "response": "yes"}},
                {"text": "also continue"},
            ]
        }
        with pytest.raises(MultimodalPayloadError, match="must not be mixed"):
            parse_payload(payload, **_LIMITS)

    def test_rejects_empty_interrupt_id(self) -> None:
        payload = {"prompt": [{"reply": {"interrupt_id": "", "response": "yes"}}]}
        with pytest.raises(MultimodalPayloadError, match="non-empty"):
            parse_payload(payload, **_LIMITS)


class TestSizeLimits:
    def test_rejects_oversize_media_block(self) -> None:
        big = b"x" * 2048
        limits = {**_LIMITS, "max_media_bytes": 1024}
        payload = {"prompt": [{"image": {"format": "png", "source": {"base64": _b64(big)}}}]}
        with pytest.raises(MultimodalPayloadError, match="max_media_bytes"):
            parse_payload(payload, **limits)

    def test_rejects_too_many_blocks(self) -> None:
        small = _b64(b"x")
        limits = {**_LIMITS, "max_media_blocks": 1}
        payload = {
            "prompt": [
                {"image": {"format": "png", "source": {"base64": small}}},
                {"document": {"format": "txt", "name": "x.txt", "source": {"base64": small}}},
            ]
        }
        with pytest.raises(MultimodalPayloadError, match="max_media_blocks"):
            parse_payload(payload, **limits)

    def test_rejects_oversize_payload(self) -> None:
        limits = {**_LIMITS, "max_payload_bytes": 10}
        with pytest.raises(MultimodalPayloadError, match="max_payload_bytes"):
            parse_payload({"prompt": "x" * 200}, **limits)

    def test_payload_size_disabled_when_none(self) -> None:
        result = _parse({"prompt": "x" * 5_000}, max_payload_bytes=None)
        assert isinstance(result, str)
