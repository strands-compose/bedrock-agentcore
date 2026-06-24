"""Tests for the public media format registry."""

from __future__ import annotations

import pytest

from strands_compose_agentcore import (
    DOCUMENT_FORMATS,
    IMAGE_FORMATS,
    MEDIA_FORMATS,
    MediaFormatSpec,
)
from strands_compose_agentcore.media_formats import MEDIA_FORMATS as _MEDIA_FORMATS_DIRECT


class TestMediaFormatSpec:
    def test_is_frozen_dataclass(self) -> None:
        spec = MediaFormatSpec("png", "image", (".png",), "image/png")
        with pytest.raises(Exception):
            spec.format = "gif"  # ty: ignore[invalid-assignment]

    def test_fields_accessible(self) -> None:
        spec = MediaFormatSpec("jpeg", "image", (".jpg", ".jpeg"), "image/jpeg")
        assert spec.format == "jpeg"
        assert spec.category == "image"
        assert spec.extensions == (".jpg", ".jpeg")
        assert spec.mime_type == "image/jpeg"

    def test_equality_by_value(self) -> None:
        a = MediaFormatSpec("png", "image", (".png",), "image/png")
        b = MediaFormatSpec("png", "image", (".png",), "image/png")
        assert a == b


class TestMediaFormatsRegistry:
    def test_is_tuple_of_specs(self) -> None:
        assert isinstance(MEDIA_FORMATS, tuple)
        assert all(isinstance(s, MediaFormatSpec) for s in MEDIA_FORMATS)

    def test_contains_all_image_formats(self) -> None:
        registry_image = {s.format for s in MEDIA_FORMATS if s.category == "image"}
        assert registry_image == IMAGE_FORMATS

    def test_contains_all_document_formats(self) -> None:
        registry_doc = {s.format for s in MEDIA_FORMATS if s.category == "document"}
        assert registry_doc == DOCUMENT_FORMATS

    def test_all_formats_have_category_image_or_document(self) -> None:
        categories = {s.category for s in MEDIA_FORMATS}
        assert categories <= {"image", "document"}

    def test_all_extensions_start_with_dot(self) -> None:
        for spec in MEDIA_FORMATS:
            for ext in spec.extensions:
                assert ext.startswith("."), "extension %r in %r must start with dot" % (
                    ext,
                    spec.format,
                )

    def test_all_formats_have_at_least_one_extension(self) -> None:
        for spec in MEDIA_FORMATS:
            assert spec.extensions, "format %r must have at least one extension" % spec.format

    def test_all_mime_types_non_empty(self) -> None:
        for spec in MEDIA_FORMATS:
            assert spec.mime_type, "format %r must have a mime_type" % spec.format

    def test_format_tokens_unique(self) -> None:
        tokens = [s.format for s in MEDIA_FORMATS]
        assert len(tokens) == len(set(tokens)), "format tokens must be unique"

    def test_jpeg_has_jpg_and_jpeg_extensions(self) -> None:
        jpeg = next(s for s in MEDIA_FORMATS if s.format == "jpeg")
        assert ".jpg" in jpeg.extensions
        assert ".jpeg" in jpeg.extensions

    def test_html_has_html_and_htm_extensions(self) -> None:
        html = next(s for s in MEDIA_FORMATS if s.format == "html")
        assert ".html" in html.extensions
        assert ".htm" in html.extensions

    def test_same_object_as_direct_import(self) -> None:
        assert MEDIA_FORMATS is _MEDIA_FORMATS_DIRECT


class TestDerivedFrozensets:
    def test_image_formats_derived_correctly(self) -> None:
        assert IMAGE_FORMATS == {"png", "jpeg", "gif", "webp"}

    def test_document_formats_derived_correctly(self) -> None:
        assert DOCUMENT_FORMATS == {"pdf", "csv", "doc", "docx", "xls", "xlsx", "html", "txt", "md"}

    def test_image_and_document_formats_disjoint(self) -> None:
        assert IMAGE_FORMATS.isdisjoint(DOCUMENT_FORMATS)


@pytest.mark.parametrize(
    "fmt,category,mime",
    [
        ("png", "image", "image/png"),
        ("jpeg", "image", "image/jpeg"),
        ("gif", "image", "image/gif"),
        ("webp", "image", "image/webp"),
        ("pdf", "document", "application/pdf"),
        ("csv", "document", "text/csv"),
        ("doc", "document", "application/msword"),
        (
            "docx",
            "document",
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        ),
        ("xls", "document", "application/vnd.ms-excel"),
        (
            "xlsx",
            "document",
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        ),
        ("html", "document", "text/html"),
        ("txt", "document", "text/plain"),
        ("md", "document", "text/markdown"),
    ],
)
def test_each_format_spec_values(fmt: str, category: str, mime: str) -> None:
    spec = next((s for s in MEDIA_FORMATS if s.format == fmt), None)
    assert spec is not None, "format %r not found in MEDIA_FORMATS" % fmt
    assert spec.category == category
    assert spec.mime_type == mime
