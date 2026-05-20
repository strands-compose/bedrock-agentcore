"""Tests for the invocation content-block builders."""

from __future__ import annotations

import base64
from pathlib import Path

import pytest

from strands_compose_agentcore.media import document, image, reply, text


def _decode(b64: str) -> bytes:
    return base64.b64decode(b64)


class TestImage:
    def test_image_path_infers_format(self, tmp_path: Path) -> None:
        path = tmp_path / "cat.png"
        path.write_bytes(b"\x89PNG-data")
        block = image(path)
        assert block["image"]["format"] == "png"
        assert _decode(block["image"]["source"]["base64"]) == b"\x89PNG-data"

    def test_image_jpg_extension_maps_to_jpeg(self, tmp_path: Path) -> None:
        path = tmp_path / "cat.jpg"
        path.write_bytes(b"data")
        assert image(path)["image"]["format"] == "jpeg"

    def test_image_bytes_require_format(self) -> None:
        with pytest.raises(ValueError, match="could not infer image format"):
            image(b"\x89PNG")

    def test_image_bytes_with_format(self) -> None:
        block = image(b"\x89PNG", format="png")
        assert _decode(block["image"]["source"]["base64"]) == b"\x89PNG"

    def test_image_rejects_document_format(self) -> None:
        with pytest.raises(ValueError, match="not a supported image format"):
            image(b"x", format="pdf")  # ty: ignore[invalid-argument-type]


class TestDocument:
    def test_document_path_infers_format_and_name(self, tmp_path: Path) -> None:
        path = tmp_path / "spec.md"
        path.write_bytes(b"# heading")
        block = document(path)
        assert block["document"]["format"] == "md"
        # Auto-inferred name gets an 8-hex-char suffix for Bedrock uniqueness
        assert block["document"]["name"].startswith("spec-")
        assert len(block["document"]["name"]) == len("spec-") + 8
        assert _decode(block["document"]["source"]["base64"]) == b"# heading"

    def test_document_suffix_is_unique_per_call(self, tmp_path: Path) -> None:
        path = tmp_path / "spec.md"
        path.write_bytes(b"# heading")
        names = {document(path)["document"]["name"] for _ in range(20)}
        assert len(names) == 20, "auto-inferred names should differ across calls"

    def test_document_name_override(self, tmp_path: Path) -> None:
        path = tmp_path / "spec.md"
        path.write_bytes(b"# heading")
        assert document(path, name="Final.md")["document"]["name"] == "Final.md"

    def test_document_bytes_require_format(self) -> None:
        with pytest.raises(ValueError, match="could not infer document format"):
            document(b"%PDF", name="report.pdf")

    def test_document_bytes_require_name(self) -> None:
        with pytest.raises(ValueError, match="document name"):
            document(b"%PDF", format="pdf")

    def test_document_bytes_with_format_and_name(self) -> None:
        block = document(b"%PDF", format="pdf", name="report.pdf")
        assert block["document"]["format"] == "pdf"
        assert block["document"]["name"] == "report.pdf"


class TestText:
    def test_builds_text_block(self) -> None:
        assert text("hello") == {"text": "hello"}


class TestReply:
    def test_builds_reply_block(self) -> None:
        assert reply("abc", "yes") == {"reply": {"interrupt_id": "abc", "response": "yes"}}

    def test_accepts_any_response_payload(self) -> None:
        payload = {"choice": 2, "reason": "prefer second"}
        block = reply("iid-1", payload)
        assert block["reply"]["response"] == payload
