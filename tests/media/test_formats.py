"""Invariant tests on the MEDIA_FORMATS registry.

Per the testing doctrine, the static table's field values are a data-entry
check, not a behavioural invariant -- they are not tested.  The one real
invariant is that the derived ``IMAGE_FORMATS`` / ``DOCUMENT_FORMATS`` sets
partition the table exactly.
"""

from __future__ import annotations

from strands_compose_agentcore.media_formats import MEDIA_FORMATS
from strands_compose_agentcore.types import DOCUMENT_FORMATS, IMAGE_FORMATS


class TestImageAndDocumentFormatsPartitionTheRegistry:
    """IMAGE_FORMATS and DOCUMENT_FORMATS are disjoint and cover every entry."""

    def test_image_and_document_formats_are_disjoint(self) -> None:
        assert IMAGE_FORMATS & DOCUMENT_FORMATS == frozenset()

    def test_union_covers_all_media_formats(self) -> None:
        all_formats = frozenset(s.format for s in MEDIA_FORMATS)
        assert IMAGE_FORMATS | DOCUMENT_FORMATS == all_formats
