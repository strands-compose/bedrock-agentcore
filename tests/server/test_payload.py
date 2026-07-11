"""Tests for parse_payload: string prompts, blocks, media, errors, limits."""

from __future__ import annotations

import base64

import pytest

from strands_compose_agentcore.payload import MultimodalPayloadError, parse_payload
from tests.factories import (
    document_payload,
    image_payload,
    payload,
    reply_payload,
    text_block_payload,
)

_DEFAULTS = {
    "max_payload_bytes": 25 * 1024 * 1024,
    "max_media_bytes": 20 * 1024 * 1024,
    "max_media_blocks": 20,
}


class TestParsePayloadStringPrompts:
    """parse_payload with simple string prompts."""

    def test_payload_accepts_simple_string_prompt(self) -> None:
        result = parse_payload(payload("Hello agent"), **_DEFAULTS)
        assert result == "Hello agent"

    def test_payload_accepts_unicode_string_prompt(self) -> None:
        result = parse_payload(payload("Hola mundo!"), **_DEFAULTS)
        assert result == "Hola mundo!"

    def test_payload_rejects_empty_string_prompt_with_error(self) -> None:
        with pytest.raises(MultimodalPayloadError):
            parse_payload(payload(""), **_DEFAULTS)


class TestParsePayloadTextBlocks:
    """parse_payload with text content blocks."""

    def test_payload_accepts_single_text_block(self) -> None:
        result = parse_payload(text_block_payload("Hello world"), **_DEFAULTS)
        assert isinstance(result, list)
        assert result[0] == {"text": "Hello world"}

    def test_payload_rejects_empty_text_block_with_error(self) -> None:
        with pytest.raises(MultimodalPayloadError):
            parse_payload(text_block_payload(""), **_DEFAULTS)


class TestParsePayloadImageBlocks:
    """parse_payload decodes image blocks from base64 to bytes."""

    def test_payload_decodes_image_base64_to_bytes(self) -> None:
        raw = b"\x89PNG\r\n\x1a\n" + b"\x00" * 50
        result = parse_payload(image_payload(data=raw), **_DEFAULTS)
        assert isinstance(result, list)
        block = result[0]
        assert "image" in block
        assert block["image"]["format"] == "png"  # ty: ignore[not-subscriptable]
        assert block["image"]["source"]["bytes"] == raw  # ty: ignore[not-subscriptable]

    def test_payload_accepts_jpeg_format(self) -> None:
        raw = b"\xff\xd8\xff" + b"\x00" * 50
        result = parse_payload(image_payload(format="jpeg", data=raw), **_DEFAULTS)
        assert isinstance(result, list)
        block = result[0]
        assert "image" in block
        assert block["image"]["format"] == "jpeg"  # ty: ignore[not-subscriptable]

    def test_payload_rejects_unsupported_image_format(self) -> None:
        p = {
            "prompt": [
                {
                    "image": {
                        "format": "bmp",
                        "source": {"base64": base64.b64encode(b"x" * 10).decode()},
                    }
                }
            ]
        }
        with pytest.raises(MultimodalPayloadError):
            parse_payload(p, **_DEFAULTS)


class TestParsePayloadDocumentBlocks:
    """parse_payload decodes document blocks."""

    def test_payload_decodes_document_base64_to_bytes(self) -> None:
        raw = b"%PDF-1.4" + b"\x00" * 50
        result = parse_payload(document_payload(data=raw), **_DEFAULTS)
        assert isinstance(result, list)
        block = result[0]
        assert "document" in block
        assert block["document"]["format"] == "pdf"  # ty: ignore[not-subscriptable]
        assert block["document"]["source"]["bytes"] == raw  # ty: ignore[not-subscriptable]
        assert block["document"]["name"] == "report"  # ty: ignore[not-subscriptable]

    def test_payload_rejects_unsupported_document_format(self) -> None:
        p = {
            "prompt": [
                {
                    "document": {
                        "format": "exe",
                        "name": "bad",
                        "source": {"base64": base64.b64encode(b"x").decode()},
                    }
                }
            ]
        }
        with pytest.raises(MultimodalPayloadError):
            parse_payload(p, **_DEFAULTS)


class TestParsePayloadReplyBlocks:
    """parse_payload handles reply blocks."""

    def test_payload_accepts_valid_reply_block(self) -> None:
        result = parse_payload(reply_payload("int-001", "yes"), **_DEFAULTS)
        assert isinstance(result, list)
        block = result[0]
        assert "interruptResponse" in block
        assert block["interruptResponse"]["interruptId"] == "int-001"  # ty: ignore[not-subscriptable]
        assert block["interruptResponse"]["response"] == "yes"  # ty: ignore[not-subscriptable]

    def test_payload_rejects_mixed_reply_and_text_blocks(self) -> None:
        p = {"prompt": [{"reply": {"interrupt_id": "x", "response": "y"}}, {"text": "hello"}]}
        with pytest.raises(MultimodalPayloadError):
            parse_payload(p, **_DEFAULTS)


class TestParsePayloadLimits:
    """parse_payload enforces size and count limits."""

    def test_payload_rejects_oversized_payload_with_error(self) -> None:
        with pytest.raises(MultimodalPayloadError, match="max_payload_bytes"):
            parse_payload(
                payload("x" * 100),
                max_payload_bytes=10,
                max_media_bytes=20 * 1024 * 1024,
                max_media_blocks=20,
            )

    def test_payload_rejects_oversized_media_with_error(self) -> None:
        big_data = b"\x00" * 100
        with pytest.raises(MultimodalPayloadError, match="max_media_bytes"):
            parse_payload(
                image_payload(data=big_data),
                max_payload_bytes=None,
                max_media_bytes=10,
                max_media_blocks=20,
            )

    def test_payload_rejects_too_many_media_blocks_with_error(self) -> None:
        blocks = [
            {
                "image": {
                    "format": "png",
                    "source": {"base64": base64.b64encode(b"\x00" * 5).decode()},
                }
            }
            for _ in range(3)
        ]
        with pytest.raises(MultimodalPayloadError, match="max_media_blocks"):
            parse_payload(
                {"prompt": blocks}, max_payload_bytes=None, max_media_bytes=1024, max_media_blocks=2
            )

    def test_payload_disables_size_check_when_max_payload_bytes_is_none(self) -> None:
        result = parse_payload(
            payload("x" * 10000),
            max_payload_bytes=None,
            max_media_bytes=20 * 1024 * 1024,
            max_media_blocks=20,
        )
        assert result == "x" * 10000


class TestParsePayloadErrors:
    """parse_payload rejects malformed inputs."""

    def test_payload_rejects_missing_prompt_field(self) -> None:
        with pytest.raises(MultimodalPayloadError, match="prompt"):
            parse_payload({}, **_DEFAULTS)

    def test_payload_rejects_empty_list_prompt(self) -> None:
        with pytest.raises(MultimodalPayloadError):
            parse_payload(payload([]), **_DEFAULTS)

    def test_payload_rejects_invalid_block_shape(self) -> None:
        with pytest.raises(MultimodalPayloadError):
            parse_payload(payload([{"text": "hi", "image": {}}]), **_DEFAULTS)

    def test_payload_rejects_non_object_block(self) -> None:
        with pytest.raises(MultimodalPayloadError):
            parse_payload(payload([42]), **_DEFAULTS)

    def test_payload_rejects_invalid_base64_source(self) -> None:
        p = {"prompt": [{"image": {"format": "png", "source": {"base64": "!!!invalid!!!"}}}]}
        with pytest.raises(MultimodalPayloadError, match="base64"):
            parse_payload(p, **_DEFAULTS)
