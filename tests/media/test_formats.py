"""Invariant tests on the MEDIA_FORMATS registry.

Per the testing doctrine, the static table's field values are a data-entry
check, not a behavioural invariant -- they are not tested.  The one real
invariant is that the derived ``IMAGE_FORMATS`` / ``DOCUMENT_FORMATS`` sets
partition the table exactly.
"""

from __future__ import annotations

from typing import get_args

from strands_compose_agentcore.media_formats import MEDIA_FORMATS
from strands_compose_agentcore.types import (
    DOCUMENT_FORMATS,
    IMAGE_FORMATS,
    DocumentFormat,
    ImageFormat,
)


class TestImageAndDocumentFormatsPartitionTheRegistry:
    """IMAGE_FORMATS and DOCUMENT_FORMATS are disjoint and cover every entry."""

    def test_image_and_document_formats_are_disjoint(self) -> None:
        assert IMAGE_FORMATS & DOCUMENT_FORMATS == frozenset()

    def test_union_covers_all_media_formats(self) -> None:
        all_formats = frozenset(s.format for s in MEDIA_FORMATS)
        assert IMAGE_FORMATS | DOCUMENT_FORMATS == all_formats


class TestLiteralsMatchTheRegistry:
    """The public Literals are the one copy of the registry a type checker sees.

    ``Literal[...]`` cannot be built from a runtime tuple, so this duplication is
    forced.  These tests are the only thing keeping the two in step.
    """

    def test_image_format_literal_matches_image_formats(self) -> None:
        assert frozenset(get_args(ImageFormat)) == IMAGE_FORMATS

    def test_document_format_literal_matches_document_formats(self) -> None:
        assert frozenset(get_args(DocumentFormat)) == DOCUMENT_FORMATS
