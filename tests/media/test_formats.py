"""Property/invariant tests on the MEDIA_FORMATS registry."""

from __future__ import annotations

import pytest

from strands_compose_agentcore.media_formats import MEDIA_FORMATS, MediaFormatSpec
from strands_compose_agentcore.types import DOCUMENT_FORMATS, IMAGE_FORMATS


class TestMediaFormatsRegistryInvariants:
    """MEDIA_FORMATS entries satisfy structural invariants."""

    @pytest.mark.parametrize("spec", MEDIA_FORMATS, ids=[s.format for s in MEDIA_FORMATS])
    def test_media_format_spec_has_non_empty_format(self, spec: MediaFormatSpec) -> None:
        assert spec.format
        assert isinstance(spec.format, str)

    @pytest.mark.parametrize("spec", MEDIA_FORMATS, ids=[s.format for s in MEDIA_FORMATS])
    def test_media_format_spec_has_valid_category(self, spec: MediaFormatSpec) -> None:
        assert spec.category in ("image", "document")

    @pytest.mark.parametrize("spec", MEDIA_FORMATS, ids=[s.format for s in MEDIA_FORMATS])
    def test_media_format_spec_has_extensions_starting_with_dot(
        self, spec: MediaFormatSpec
    ) -> None:
        assert len(spec.extensions) >= 1
        for ext in spec.extensions:
            assert ext.startswith(".")

    @pytest.mark.parametrize("spec", MEDIA_FORMATS, ids=[s.format for s in MEDIA_FORMATS])
    def test_media_format_spec_has_non_empty_mime_type(self, spec: MediaFormatSpec) -> None:
        assert spec.mime_type
        assert "/" in spec.mime_type


class TestImageAndDocumentFormatsDisjoint:
    """IMAGE_FORMATS and DOCUMENT_FORMATS are disjoint and cover all entries."""

    def test_image_and_document_formats_are_disjoint(self) -> None:
        assert IMAGE_FORMATS & DOCUMENT_FORMATS == frozenset()

    def test_union_covers_all_media_formats(self) -> None:
        all_formats = frozenset(s.format for s in MEDIA_FORMATS)
        assert IMAGE_FORMATS | DOCUMENT_FORMATS == all_formats
