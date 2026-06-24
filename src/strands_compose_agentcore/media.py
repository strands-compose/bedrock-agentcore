"""Small helpers for building JSON-safe invocation content blocks.

These builders trust their caller — they perform only the minimal work
needed to assemble a valid wire block (format inference for paths,
base64 encoding for bytes).  The server-side parser in ``payload.py``
re-validates anything that crosses the wire.
"""

from __future__ import annotations

import base64
import uuid
from pathlib import Path
from typing import Any, cast

from .media_formats import MEDIA_FORMATS
from .types import (
    DOCUMENT_FORMATS,
    IMAGE_FORMATS,
    DocumentBlock,
    DocumentFormat,
    ImageBlock,
    ImageFormat,
    MediaSource,
    ReplyBlock,
    TextBlock,
)

_IMAGE_EXTENSIONS: dict[str, str] = {
    ext: s.format for s in MEDIA_FORMATS if s.category == "image" for ext in s.extensions
}
_DOCUMENT_EXTENSIONS: dict[str, str] = {
    ext: s.format for s in MEDIA_FORMATS if s.category == "document" for ext in s.extensions
}


def text(value: str) -> TextBlock:
    """Build a text content block."""
    return {"text": value}


def image(source: str | Path | bytes, *, format: ImageFormat | None = None) -> ImageBlock:
    """Build an image content block from a local path or bytes.

    Args:
        source: Local filesystem path or raw image bytes.
        format: Image format.  Required for raw bytes and inferred from
            the file extension for paths when omitted.

    Raises:
        FileNotFoundError: ``source`` is a path that does not exist.
        ValueError: The format cannot be inferred or is unsupported.
    """
    payload, extension, _ = _read_local_source(source)
    resolved_format = _resolve_format(
        kind="image",
        supplied=format,
        extension=extension,
        extension_map=_IMAGE_EXTENSIONS,
        allowed=IMAGE_FORMATS,
    )
    return cast(
        ImageBlock,
        {
            "image": {
                "format": cast(ImageFormat, resolved_format),
                "source": _encoded_source(payload),
            }
        },
    )


def document(
    source: str | Path | bytes,
    *,
    format: DocumentFormat | None = None,
    name: str | None = None,
) -> DocumentBlock:
    """Build a document content block from a local path or bytes.

    Args:
        source: Local filesystem path or raw document bytes.
        format: Document format.  Required for raw bytes and inferred
            from the file extension for paths when omitted.
        name: Document name sent to the agent.  When omitted, the file
            stem is used with a short random suffix appended
            (e.g. ``"report-a1b2c3d4"``).  The suffix ensures names
            stay unique across conversation turns — Bedrock's Converse
            API rejects duplicate document names within the same
            session history.  Pass ``name=`` explicitly to take full
            control of the name (no suffix is added).

    Raises:
        FileNotFoundError: ``source`` is a path that does not exist.
        ValueError: The format cannot be inferred, is unsupported, or
            a document name cannot be chosen.
    """
    payload, extension, default_name = _read_local_source(source)
    resolved_format = _resolve_format(
        kind="document",
        supplied=format,
        extension=extension,
        extension_map=_DOCUMENT_EXTENSIONS,
        allowed=DOCUMENT_FORMATS,
    )
    if name is not None:
        resolved_name: str | None = name
    elif default_name:
        resolved_name = "%s-%s" % (default_name, uuid.uuid4().hex[:8])
    else:
        resolved_name = None
    if not resolved_name:
        raise ValueError("document name must not be empty; pass name= explicitly")
    return cast(
        DocumentBlock,
        {
            "document": {
                "format": cast(DocumentFormat, resolved_format),
                "name": resolved_name,
                "source": _encoded_source(payload),
            }
        },
    )


def reply(interrupt_id: str, response: Any) -> ReplyBlock:
    """Build a reply block for resuming a pending interrupt."""
    return {"reply": {"interrupt_id": interrupt_id, "response": response}}


def _read_local_source(source: str | Path | bytes) -> tuple[bytes, str | None, str | None]:
    """Return ``(bytes, extension, default_name)`` for a path or raw bytes.

    Paths must point to an existing local file.
    Raises ``FileNotFoundError`` if not found.
    """
    if isinstance(source, bytes):
        return source, None, None
    path = Path(source)
    return path.read_bytes(), path.suffix.lower(), path.stem


def _resolve_format(
    *,
    kind: str,
    supplied: str | None,
    extension: str | None,
    extension_map: dict[str, str],
    allowed: frozenset[str],
) -> str:
    """Resolve and validate a media format."""
    resolved = supplied if supplied is not None else extension_map.get(extension or "")
    if resolved is None:
        raise ValueError("could not infer %s format; pass format= explicitly" % kind)
    if resolved not in allowed:
        raise ValueError("format %r is not a supported %s format" % (resolved, kind))
    return resolved


def _encoded_source(payload: bytes) -> MediaSource:
    """Encode bytes into the JSON wire source shape."""
    return {"base64": base64.b64encode(payload).decode("ascii")}
