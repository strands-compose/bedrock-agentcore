"""Tests for the multimodal content-block builders in ``media.py``."""

from __future__ import annotations

import base64
from pathlib import Path

import pytest

from strands_compose_agentcore.media import (
    document_block,
    image_block,
    s3_document_block,
    s3_image_block,
)


def _decode(b64: str) -> bytes:
    return base64.b64decode(b64)


class TestImageBlock:
    def test_from_bytes_with_explicit_format(self) -> None:
        block = image_block(b"\x89PNG", format="png")
        assert block["image"]["format"] == "png"
        assert _decode(block["image"]["source"]["base64"]) == b"\x89PNG"

    def test_from_bytes_requires_format(self) -> None:
        with pytest.raises(ValueError, match="format= is required"):
            image_block(b"\x89PNG")

    def test_from_path_infers_format_png(self, tmp_path: Path) -> None:
        path = tmp_path / "cat.png"
        path.write_bytes(b"\x89PNG-data")
        block = image_block(path)
        assert block["image"]["format"] == "png"
        assert _decode(block["image"]["source"]["base64"]) == b"\x89PNG-data"

    def test_from_path_infers_jpeg_from_jpg(self, tmp_path: Path) -> None:
        path = tmp_path / "cat.jpg"
        path.write_bytes(b"data")
        block = image_block(path)
        assert block["image"]["format"] == "jpeg"

    def test_from_path_explicit_format_overrides(self, tmp_path: Path) -> None:
        path = tmp_path / "cat.bin"
        path.write_bytes(b"data")
        block = image_block(path, format="webp")
        assert block["image"]["format"] == "webp"

    def test_unknown_extension_raises(self, tmp_path: Path) -> None:
        path = tmp_path / "blob.bin"
        path.write_bytes(b"x")
        with pytest.raises(ValueError, match="could not infer image format"):
            image_block(path)


class TestDocumentBlock:
    def test_from_bytes(self) -> None:
        block = document_block(b"%PDF", format="pdf", name="report.pdf")
        assert block["document"]["format"] == "pdf"
        assert block["document"]["name"] == "report.pdf"
        assert _decode(block["document"]["source"]["base64"]) == b"%PDF"

    def test_from_path(self, tmp_path: Path) -> None:
        path = tmp_path / "spec.md"
        path.write_bytes(b"# heading")
        block = document_block(path, format="md", name="spec.md")
        assert _decode(block["document"]["source"]["base64"]) == b"# heading"

    def test_rejects_empty_name(self) -> None:
        with pytest.raises(ValueError, match="name"):
            document_block(b"x", format="txt", name="")


class TestS3Helpers:
    def test_s3_image_block(self) -> None:
        block = s3_image_block("s3://bucket/key.png", format="png", bucket_owner="111")
        assert block["image"]["source"]["location"] == {
            "type": "s3",
            "uri": "s3://bucket/key.png",
            "bucketOwner": "111",
        }

    def test_s3_image_block_without_owner(self) -> None:
        block = s3_image_block("s3://bucket/key.png", format="png")
        assert "bucketOwner" not in block["image"]["source"]["location"]

    def test_s3_image_block_rejects_non_s3_uri(self) -> None:
        with pytest.raises(ValueError, match="s3://"):
            s3_image_block("https://example.com/x.png", format="png")

    def test_s3_document_block(self) -> None:
        block = s3_document_block(
            "s3://bucket/x.pdf", format="pdf", name="x.pdf", bucket_owner="222"
        )
        assert block["document"]["name"] == "x.pdf"
        assert block["document"]["source"]["location"]["bucketOwner"] == "222"

    def test_s3_document_block_rejects_empty_name(self) -> None:
        with pytest.raises(ValueError, match="name"):
            s3_document_block("s3://b/x.pdf", format="pdf", name="")
