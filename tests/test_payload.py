"""Tests for the multimodal payload parser."""

from __future__ import annotations

import base64
from typing import Any

import pytest

from strands_compose_agentcore.payload import (
    MultimodalPayloadError,
    describe_input,
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

    def test_rejects_non_string_prompt(self) -> None:
        with pytest.raises(MultimodalPayloadError, match="must be a string"):
            parse_payload({"prompt": 42}, **_LIMITS)


class TestParseExclusivity:
    def test_rejects_missing_all(self) -> None:
        with pytest.raises(MultimodalPayloadError, match="missing required field"):
            parse_payload({}, **_LIMITS)

    def test_rejects_multiple(self) -> None:
        with pytest.raises(MultimodalPayloadError, match="exactly one"):
            parse_payload({"prompt": "hi", "content": [{"text": "x"}]}, **_LIMITS)

    def test_rejects_non_mapping(self) -> None:
        with pytest.raises(MultimodalPayloadError, match="must be a JSON object"):
            parse_payload("hi", **_LIMITS)  # ty: ignore[invalid-argument-type]


class TestParseContent:
    def test_text_content_passes_through(self) -> None:
        result = parse_payload({"content": [{"text": "describe"}]}, **_LIMITS)
        assert result == [{"text": "describe"}]

    def test_image_base64_decoded_to_bytes(self) -> None:
        raw = b"\x89PNG\r\n"
        encoded = _b64(raw)
        payload = {
            "content": [
                {"image": {"format": "png", "source": {"base64": encoded}}},
                {"text": "what is this"},
            ]
        }
        result = _parse(payload)
        assert isinstance(result, list)
        assert result[0]["image"]["source"] == {"bytes": raw}
        assert result[1] == {"text": "what is this"}

    def test_s3_location_passed_through(self) -> None:
        payload = {
            "content": [
                {
                    "image": {
                        "format": "png",
                        "source": {
                            "location": {
                                "type": "s3",
                                "uri": "s3://bucket/key.png",
                                "bucketOwner": "1234",
                            }
                        },
                    }
                }
            ]
        }
        result = _parse(payload)
        assert result[0]["image"]["source"]["location"]["uri"] == "s3://bucket/key.png"

    def test_rejects_empty_content(self) -> None:
        with pytest.raises(MultimodalPayloadError, match="non-empty"):
            parse_payload({"content": []}, **_LIMITS)

    def test_rejects_non_list_content(self) -> None:
        with pytest.raises(MultimodalPayloadError):
            parse_payload({"content": {"text": "x"}}, **_LIMITS)

    def test_rejects_non_dict_block(self) -> None:
        with pytest.raises(MultimodalPayloadError, match="JSON object"):
            parse_payload({"content": ["not-a-block"]}, **_LIMITS)

    def test_preserves_unknown_keys(self) -> None:
        payload = {
            "content": [
                {"reasoningContent": {"reasoningText": {"text": "future"}}},
                {"text": "ok"},
            ]
        }
        result = _parse(payload)
        assert result[0]["reasoningContent"]["reasoningText"]["text"] == "future"


class TestParseMessages:
    def test_full_conversation(self) -> None:
        payload = {
            "messages": [
                {"role": "user", "content": [{"text": "hello"}]},
                {"role": "assistant", "content": [{"text": "hi"}]},
            ]
        }
        result = _parse(payload)
        assert len(result) == 2
        assert result[0]["role"] == "user"

    def test_rejects_invalid_role(self) -> None:
        with pytest.raises(MultimodalPayloadError, match="role"):
            parse_payload({"messages": [{"role": "system", "content": [{"text": "x"}]}]}, **_LIMITS)

    def test_rejects_missing_content(self) -> None:
        with pytest.raises(MultimodalPayloadError, match="non-empty list"):
            parse_payload({"messages": [{"role": "user"}]}, **_LIMITS)

    def test_rejects_non_dict_message(self) -> None:
        with pytest.raises(MultimodalPayloadError, match="message must be"):
            parse_payload({"messages": ["bad"]}, **_LIMITS)

    def test_rejects_empty(self) -> None:
        with pytest.raises(MultimodalPayloadError, match="non-empty"):
            parse_payload({"messages": []}, **_LIMITS)


class TestSourceDecoding:
    def test_rejects_base64_with_bytes(self) -> None:
        payload = {
            "content": [{"image": {"format": "png", "source": {"base64": "AAA=", "bytes": b"x"}}}]
        }
        with pytest.raises(MultimodalPayloadError, match="only one"):
            parse_payload(payload, **_LIMITS)

    def test_rejects_base64_with_location(self) -> None:
        payload = {
            "content": [
                {
                    "image": {
                        "format": "png",
                        "source": {
                            "base64": "AAA=",
                            "location": {"type": "s3", "uri": "s3://b/k"},
                        },
                    }
                }
            ]
        }
        with pytest.raises(MultimodalPayloadError):
            parse_payload(payload, **_LIMITS)

    def test_rejects_non_string_base64(self) -> None:
        payload = {"content": [{"image": {"format": "png", "source": {"base64": 1}}}]}
        with pytest.raises(MultimodalPayloadError, match="must be a string"):
            parse_payload(payload, **_LIMITS)

    def test_rejects_malformed_base64(self) -> None:
        payload = {"content": [{"image": {"format": "png", "source": {"base64": "!!!"}}}]}
        with pytest.raises(MultimodalPayloadError, match="valid base64"):
            parse_payload(payload, **_LIMITS)

    def test_decodes_video_source(self) -> None:
        # generic walk should handle video blocks too
        raw = b"\x00\x00mp4"
        payload = {"content": [{"video": {"format": "mp4", "source": {"base64": _b64(raw)}}}]}
        result = _parse(payload)
        assert result[0]["video"]["source"] == {"bytes": raw}

    def test_decodes_document_source(self) -> None:
        raw = b"%PDF-1.4"
        payload = {
            "content": [
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

    def test_leaves_unknown_source_fields_untouched(self) -> None:
        payload = {"content": [{"image": {"format": "png", "source": {"future": "value"}}}]}
        result = _parse(payload)
        assert result[0]["image"]["source"] == {"future": "value"}


class TestSizeLimits:
    def test_rejects_oversize_media_block(self) -> None:
        big = b"x" * 2048
        limits = {**_LIMITS, "max_media_bytes": 1024}
        payload = {"content": [{"image": {"format": "png", "source": {"base64": _b64(big)}}}]}
        with pytest.raises(MultimodalPayloadError, match="max_media_bytes"):
            parse_payload(payload, **limits)

    def test_rejects_too_many_blocks(self) -> None:
        small = _b64(b"x")
        limits = {**_LIMITS, "max_media_blocks": 1}
        payload = {
            "content": [
                {"image": {"format": "png", "source": {"base64": small}}},
                {"image": {"format": "png", "source": {"base64": small}}},
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

    def test_s3_location_counts_against_block_cap(self) -> None:
        limits = {**_LIMITS, "max_media_blocks": 1}
        payload = {
            "content": [
                {
                    "image": {
                        "format": "png",
                        "source": {"location": {"type": "s3", "uri": "s3://a/1"}},
                    }
                },
                {
                    "image": {
                        "format": "png",
                        "source": {"location": {"type": "s3", "uri": "s3://a/2"}},
                    }
                },
            ]
        }
        with pytest.raises(MultimodalPayloadError, match="max_media_blocks"):
            parse_payload(payload, **limits)


class TestDescribeInput:
    def test_none(self) -> None:
        assert describe_input(None) == "None"

    def test_string_truncates(self) -> None:
        result = describe_input("hello world")
        assert "hello world" in result

    def test_messages(self) -> None:
        msgs = [{"role": "user", "content": [{"text": "x"}]}]
        assert "messages:count=1" in describe_input(msgs)

    def test_content(self) -> None:
        assert "content:count=2" in describe_input([{"text": "a"}, {"text": "b"}])

    def test_empty_list(self) -> None:
        assert describe_input([]) == "list:empty"
