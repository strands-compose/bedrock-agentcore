"""Tests for media builders: text(), image(), document(), reply()."""

from __future__ import annotations

import base64
import tempfile
from pathlib import Path

import pytest

from strands_compose_agentcore.media import document, image, reply, text


class TestTextBuilder:
    """text() returns a TextBlock shape."""

    def test_text_returns_text_block(self) -> None:
        result = text("hello world")
        assert result == {"text": "hello world"}


class TestImageBuilder:
    """image() builds ImageBlock with base64 encoding."""

    def test_image_from_bytes_with_format_returns_image_block(self) -> None:
        raw = b"\x89PNG\r\n\x1a\n" + b"\x00" * 10
        result = image(raw, format="png")
        assert "image" in result
        assert result["image"]["format"] == "png"
        assert result["image"]["source"]["base64"] == base64.b64encode(raw).decode("ascii")

    def test_image_from_path_infers_format_from_extension(self) -> None:
        raw = b"\x89PNG\r\n\x1a\n"
        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
            f.write(raw)
            f.flush()
            path = Path(f.name)

        result = image(path)
        assert result["image"]["format"] == "png"
        assert result["image"]["source"]["base64"] == base64.b64encode(raw).decode("ascii")
        path.unlink()

    def test_image_from_bytes_without_format_raises_value_error(self) -> None:
        raw = b"\x89PNG\r\n\x1a\n"
        with pytest.raises(ValueError, match="format"):
            image(raw)

    def test_image_from_nonexistent_path_raises_file_not_found_error(self) -> None:
        with pytest.raises(FileNotFoundError):
            image("/nonexistent/path/image.png")


class TestDocumentBuilder:
    """document() builds DocumentBlock from path or bytes."""

    def test_document_from_path_generates_name_with_random_suffix(self) -> None:
        raw = b"%PDF-1.4"
        with tempfile.NamedTemporaryFile(suffix=".pdf", prefix="report_", delete=False) as f:
            f.write(raw)
            f.flush()
            path = Path(f.name)

        result = document(path)
        assert "document" in result
        assert result["document"]["format"] == "pdf"
        # Name should start with the stem and have a random suffix
        name = result["document"]["name"]
        assert name.startswith(path.stem)
        assert len(name) > len(path.stem)
        path.unlink()

    def test_document_with_explicit_name_uses_it(self) -> None:
        raw = b"%PDF-1.4"
        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as f:
            f.write(raw)
            f.flush()
            path = Path(f.name)

        result = document(path, name="my-doc")
        assert result["document"]["name"] == "my-doc"
        path.unlink()

    def test_document_from_bytes_with_format_and_name(self) -> None:
        raw = b"hello,world"
        result = document(raw, format="csv", name="data")
        assert result["document"]["format"] == "csv"
        assert result["document"]["name"] == "data"
        assert result["document"]["source"]["base64"] == base64.b64encode(raw).decode("ascii")


class TestReplyBuilder:
    """reply() returns the correct wire shape."""

    def test_reply_returns_correct_shape(self) -> None:
        result = reply("int-001", "yes")
        assert result == {"reply": {"interrupt_id": "int-001", "response": "yes"}}

    def test_reply_accepts_complex_response(self) -> None:
        result = reply("int-002", {"choice": "option_a", "details": [1, 2, 3]})
        assert result["reply"]["interrupt_id"] == "int-002"
        assert result["reply"]["response"] == {"choice": "option_a", "details": [1, 2, 3]}
