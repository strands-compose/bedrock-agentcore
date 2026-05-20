"""Client-side helpers that build multimodal ``ContentBlock`` dicts.

Pure builders — no network calls.  Each helper returns a JSON-ready
dict that follows the Strands ``ContentBlock`` shape and can be passed
straight to :class:`~strands_compose_agentcore.LocalClient` or
:class:`~strands_compose_agentcore.AgentCoreClient` via ``content=``.

Example::

    from strands_compose_agentcore import LocalClient, image_block

    for event in LocalClient().invoke(
        content=[image_block("cat.png"), {"text": "Describe this image"}],
    ):
        print(event.type, event.data)
"""

from __future__ import annotations

import base64
import logging
import os
from pathlib import Path
from typing import Any

from collections.abc import Mapping

from strands.types.media import DocumentFormat, ImageFormat

logger = logging.getLogger(__name__)

__all__ = [
    "document_block",
    "image_block",
    "s3_document_block",
    "s3_image_block",
]


_IMAGE_EXT_MAP: dict[str, ImageFormat] = {
    ".png": "png",
    ".jpg": "jpeg",
    ".jpeg": "jpeg",
    ".gif": "gif",
    ".webp": "webp",
}


def image_block(
    path_or_bytes: str | os.PathLike[str] | bytes,
    *,
    format: ImageFormat | None = None,
) -> dict[str, Any]:
    """Build an ``image`` content block from a file path or raw bytes.

    The block uses the JSON-safe ``source.base64`` synonym; the server
    decodes it back into ``source.bytes`` before invoking the agent.

    Args:
        path_or_bytes: Either a filesystem path (``str`` or
            ``PathLike``) or the raw image bytes.
        format: Image format override.  Required when ``path_or_bytes``
            is ``bytes``.  When ``path_or_bytes`` is a path, the format
            is inferred from the file extension if not supplied.

    Returns:
        A dict shaped as ``{"image": {"format": ..., "source": {"base64": ...}}}``.

    Raises:
        ValueError: When ``format`` cannot be inferred or is not a
            supported image format.
    """
    payload, resolved_format = _load_media(path_or_bytes, format, _IMAGE_EXT_MAP, "image")
    return {
        "image": {
            "format": resolved_format,
            "source": {"base64": base64.b64encode(payload).decode("ascii")},
        }
    }


def document_block(
    path_or_bytes: str | os.PathLike[str] | bytes,
    *,
    format: DocumentFormat,
    name: str,
) -> dict[str, Any]:
    """Build a ``document`` content block from a file path or raw bytes.

    Args:
        path_or_bytes: Either a filesystem path or the raw document bytes.
        format: Document format (e.g. ``"pdf"``, ``"txt"``, ``"md"``).
        name: Human-readable document name surfaced to the model.

    Returns:
        A dict shaped as
        ``{"document": {"format": ..., "name": ..., "source": {"base64": ...}}}``.

    Raises:
        ValueError: When ``name`` is empty.
    """
    if not name:
        raise ValueError("document name must not be empty")
    payload = _read_bytes(path_or_bytes)
    return {
        "document": {
            "format": format,
            "name": name,
            "source": {"base64": base64.b64encode(payload).decode("ascii")},
        }
    }


def s3_image_block(
    uri: str,
    *,
    format: ImageFormat,
    bucket_owner: str | None = None,
) -> dict[str, Any]:
    """Build an ``image`` content block that points to an S3 object.

    The server passes the location through to Bedrock unchanged — no
    bytes are uploaded by the client.

    Args:
        uri: ``s3://bucket/key`` URI of the image.
        format: Image format (must be a supported Strands format).
        bucket_owner: Optional AWS account ID that owns the bucket
            when it differs from the caller's account.

    Returns:
        A dict shaped as
        ``{"image": {"format": ..., "source": {"location": {"type": "s3", ...}}}}``.

    Raises:
        ValueError: When ``uri`` does not start with ``s3://``.
    """
    location = _s3_location(uri, bucket_owner)
    return {"image": {"format": format, "source": {"location": location}}}


def s3_document_block(
    uri: str,
    *,
    format: DocumentFormat,
    name: str,
    bucket_owner: str | None = None,
) -> dict[str, Any]:
    """Build a ``document`` content block that points to an S3 object.

    Args:
        uri: ``s3://bucket/key`` URI of the document.
        format: Document format.
        name: Human-readable document name surfaced to the model.
        bucket_owner: Optional AWS account ID that owns the bucket.

    Returns:
        A dict shaped as
        ``{"document": {"format": ..., "name": ..., "source": {"location": ...}}}``.

    Raises:
        ValueError: When ``uri`` does not start with ``s3://`` or
            ``name`` is empty.
    """
    if not name:
        raise ValueError("document name must not be empty")
    location = _s3_location(uri, bucket_owner)
    return {"document": {"format": format, "name": name, "source": {"location": location}}}


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _load_media(
    path_or_bytes: str | os.PathLike[str] | bytes,
    format: str | None,
    ext_map: Mapping[str, str],
    kind: str,
) -> tuple[bytes, str]:
    """Resolve raw bytes plus a media-format string."""
    if isinstance(path_or_bytes, bytes):
        if format is None:
            raise ValueError("format= is required when passing raw bytes for %s" % kind)
        return path_or_bytes, format

    path = Path(path_or_bytes)
    payload = path.read_bytes()
    if format is not None:
        return payload, format

    inferred = ext_map.get(path.suffix.lower())
    if inferred is None:
        raise ValueError(
            "could not infer %s format from extension %r; pass format= explicitly"
            % (kind, path.suffix)
        )
    return payload, inferred


def _read_bytes(path_or_bytes: str | os.PathLike[str] | bytes) -> bytes:
    """Read raw bytes from a path, or return the input if already bytes."""
    if isinstance(path_or_bytes, bytes):
        return path_or_bytes
    return Path(path_or_bytes).read_bytes()


def _s3_location(uri: str, bucket_owner: str | None) -> dict[str, Any]:
    """Build an S3 ``location`` dict for a media source."""
    if not uri.startswith("s3://"):
        raise ValueError("S3 URI must start with 's3://', got %r" % uri)
    location: dict[str, Any] = {"type": "s3", "uri": uri}
    if bucket_owner:
        location["bucketOwner"] = bucket_owner
    return location
