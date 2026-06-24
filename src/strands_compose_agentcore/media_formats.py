"""Canonical registry of supported attachment media formats.

This module is the single source of truth for every format token, category,
file extension, and MIME type recognised by the package.  All other modules
derive their format sets and extension maps from :data:`MEDIA_FORMATS` rather
than maintaining parallel hand-written tables.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class MediaFormatSpec:
    """Canonical metadata for one supported attachment format.

    Args:
        format: The agentcore format token (e.g. ``"png"``, ``"pdf"``).
        category: The grouping category — ``"image"`` or ``"document"``.
        extensions: Leading-dot file extensions; the first entry is the
            canonical extension (e.g. ``(".jpg", ".jpeg")``).
        mime_type: The canonical MIME type (e.g. ``"image/png"``).
    """

    format: str
    category: str
    extensions: tuple[str, ...]
    mime_type: str


MEDIA_FORMATS: tuple[MediaFormatSpec, ...] = (
    MediaFormatSpec("png", "image", (".png",), "image/png"),
    MediaFormatSpec("jpeg", "image", (".jpg", ".jpeg"), "image/jpeg"),
    MediaFormatSpec("gif", "image", (".gif",), "image/gif"),
    MediaFormatSpec("webp", "image", (".webp",), "image/webp"),
    MediaFormatSpec("pdf", "document", (".pdf",), "application/pdf"),
    MediaFormatSpec("csv", "document", (".csv",), "text/csv"),
    MediaFormatSpec("doc", "document", (".doc",), "application/msword"),
    MediaFormatSpec(
        "docx",
        "document",
        (".docx",),
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ),
    MediaFormatSpec("xls", "document", (".xls",), "application/vnd.ms-excel"),
    MediaFormatSpec(
        "xlsx",
        "document",
        (".xlsx",),
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    ),
    MediaFormatSpec("html", "document", (".html", ".htm"), "text/html"),
    MediaFormatSpec("txt", "document", (".txt",), "text/plain"),
    MediaFormatSpec("md", "document", (".md",), "text/markdown"),
)
