"""Invocation payload parsing for the ``/invocations`` entrypoint.

The wire contract carries a single key, ``prompt``, whose value mirrors
the polymorphic ``AgentInput`` accepted by ``strands.Agent.__call__``:

* a non-empty ``str``;
* a single ``text`` / ``image`` / ``document`` / ``reply`` block dict;
* a non-empty list of such block dicts.

Image and document blocks carry JSON-safe ``source.base64`` bytes.  The
parser decodes those into Strands' native ``source.bytes`` shape before
the entry agent is invoked.  ``reply`` blocks are converted into
Strands interrupt responses.
"""

from __future__ import annotations

import base64
import binascii
import json
from collections.abc import Callable, Mapping
from typing import Any, cast

from strands.types.agent import AgentInput as StrandsAgentInput
from strands.types.content import ContentBlock as StrandsContentBlock
from strands.types.interrupt import InterruptResponseContent

from .types import DOCUMENT_FORMATS, IMAGE_FORMATS


class MultimodalPayloadError(ValueError):
    """Raised when an ``/invocations`` payload cannot be parsed."""


_CONTENT_KEYS: frozenset[str] = frozenset({"text", "image", "document", "reply"})


def parse_payload(
    payload: Mapping[str, Any],
    *,
    max_payload_bytes: int | None,
    max_media_bytes: int,
    max_media_blocks: int,
) -> StrandsAgentInput:
    """Translate a JSON payload into a Strands-compatible input.

    Args:
        payload: Decoded JSON request body.  Must contain a ``prompt``
            key whose value is a string, a single content block dict,
            or a non-empty list of content block dicts.
        max_payload_bytes: Maximum JSON-serialized payload size in
            bytes, or ``None`` to disable the check.
        max_media_bytes: Maximum decoded size in bytes for each image
            or document block.
        max_media_blocks: Maximum number of image/document blocks
            allowed across the invocation.

    Returns:
        A value suitable for ``Agent.invoke_async``.

    Raises:
        MultimodalPayloadError: The payload shape is invalid, media
            decoding fails, or a size/count limit is exceeded.
    """
    if not isinstance(payload, Mapping):
        raise MultimodalPayloadError("payload must be a JSON object")

    if max_payload_bytes is not None:
        try:
            encoded_size = len(json.dumps(payload).encode("utf-8"))
        except (TypeError, ValueError) as exc:
            raise MultimodalPayloadError("payload is not JSON-serializable") from exc
        if encoded_size > max_payload_bytes:
            raise MultimodalPayloadError(
                "payload size %d bytes exceeds max_payload_bytes=%d"
                % (encoded_size, max_payload_bytes)
            )

    if "prompt" not in payload:
        raise MultimodalPayloadError("missing required field: 'prompt'")

    value = payload["prompt"]

    if isinstance(value, str):
        if not value:
            raise MultimodalPayloadError("'prompt' must not be empty")
        return value

    if isinstance(value, Mapping):
        blocks: list[Any] = [value]
    elif isinstance(value, list):
        if not value:
            raise MultimodalPayloadError("'prompt' list must not be empty")
        blocks = value
    else:
        raise MultimodalPayloadError(
            "'prompt' must be a string, a content block, or a list of content blocks"
        )

    return _decode_blocks(
        blocks,
        max_media_bytes=max_media_bytes,
        max_media_blocks=max_media_blocks,
    )


def _decode_blocks(
    blocks: list[Any],
    *,
    max_media_bytes: int,
    max_media_blocks: int,
) -> StrandsAgentInput:
    """Validate and decode a list of content block dicts."""
    media_count = 0

    def _bump() -> None:
        nonlocal media_count
        media_count += 1
        if media_count > max_media_blocks:
            raise MultimodalPayloadError(
                "media block count %d exceeds max_media_blocks=%d" % (media_count, max_media_blocks)
            )

    decoded_blocks = [_decode_block(block, max_media_bytes, _bump) for block in blocks]
    reply_count = sum(1 for block in decoded_blocks if "interruptResponse" in block)
    if reply_count and reply_count != len(decoded_blocks):
        raise MultimodalPayloadError(
            "reply blocks must not be mixed with text/image/document blocks"
        )
    if reply_count:
        return cast(list[InterruptResponseContent], decoded_blocks)
    return cast(list[StrandsContentBlock], decoded_blocks)


def _decode_block(
    block: Any, max_media_bytes: int, bump_media: Callable[[], None]
) -> dict[str, Any]:
    """Decode one content block into the Strands runtime shape."""
    if not isinstance(block, Mapping):
        raise MultimodalPayloadError("each content block must be a JSON object")

    keys = [key for key in _CONTENT_KEYS if key in block]
    if len(keys) != 1 or len(block) != 1:
        raise MultimodalPayloadError(
            "each content block must contain exactly one of 'text', 'image', 'document', or 'reply'"
        )

    key = keys[0]
    if key == "text":
        return {"text": _decode_text(block[key])}
    if key == "image":
        return {"image": _decode_media(key, block[key], max_media_bytes, bump_media)}
    if key == "document":
        return {"document": _decode_media(key, block[key], max_media_bytes, bump_media)}
    return {"interruptResponse": _decode_reply(block[key])}


def _decode_text(value: Any) -> str:
    """Validate text block content."""
    if not isinstance(value, str):
        raise MultimodalPayloadError("text block must be a string")
    if not value:
        raise MultimodalPayloadError("text block must not be empty")
    return value


def _decode_media(
    kind: str,
    value: Any,
    max_media_bytes: int,
    bump_media: Callable[[], None],
) -> dict[str, Any]:
    """Decode an image or document block into the Strands media shape."""
    if not isinstance(value, Mapping):
        raise MultimodalPayloadError("%s block must be a JSON object" % kind)

    allowed_keys = {"format", "source"}
    if kind == "document":
        allowed_keys.add("name")
    if set(value) != allowed_keys:
        expected = sorted(allowed_keys)
        raise MultimodalPayloadError("%s block must contain exactly %s" % (kind, expected))

    media_format = value["format"]
    if not isinstance(media_format, str):
        raise MultimodalPayloadError("%s.format must be a string" % kind)
    allowed_formats = IMAGE_FORMATS if kind == "image" else DOCUMENT_FORMATS
    if media_format not in allowed_formats:
        raise MultimodalPayloadError("%s.format %r is not supported" % (kind, media_format))

    decoded: dict[str, Any] = {
        "format": media_format,
        "source": _decode_source(value["source"], max_media_bytes, bump_media),
    }
    if kind == "document":
        name = value["name"]
        if not isinstance(name, str) or not name:
            raise MultimodalPayloadError("document.name must be a non-empty string")
        decoded["name"] = name
    return decoded


def _decode_source(
    value: Any, max_media_bytes: int, bump_media: Callable[[], None]
) -> dict[str, bytes]:
    """Decode a JSON-safe source into Strands' native bytes source."""
    if not isinstance(value, Mapping):
        raise MultimodalPayloadError("media source must be a JSON object")
    if set(value) != {"base64"}:
        raise MultimodalPayloadError("media source must contain only 'base64'")

    encoded = value["base64"]
    if not isinstance(encoded, str):
        raise MultimodalPayloadError("media source base64 must be a string")
    try:
        decoded = base64.b64decode(encoded, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise MultimodalPayloadError("media source is not valid base64") from exc
    if len(decoded) > max_media_bytes:
        raise MultimodalPayloadError(
            "media block size %d bytes exceeds max_media_bytes=%d" % (len(decoded), max_media_bytes)
        )
    bump_media()
    return {"bytes": decoded}


def _decode_reply(value: Any) -> dict[str, Any]:
    """Decode a public reply block into a Strands interrupt response."""
    if not isinstance(value, Mapping):
        raise MultimodalPayloadError("reply block must be a JSON object")
    if set(value) != {"interrupt_id", "response"}:
        raise MultimodalPayloadError(
            "reply block must contain exactly 'interrupt_id' and 'response'"
        )

    interrupt_id = value["interrupt_id"]
    if not isinstance(interrupt_id, str) or not interrupt_id:
        raise MultimodalPayloadError("reply.interrupt_id must be a non-empty string")
    return {"interruptId": interrupt_id, "response": value["response"]}
