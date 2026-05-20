"""Multimodal payload parsing for the ``/invocations`` entrypoint.

Pure functions — no I/O.  Accepts the JSON payload from a client and
returns a fully-typed :data:`strands.types.agent.AgentInput` ready for
``entry.invoke_async``.

The wire contract accepts **exactly one** of three mutually-exclusive
keys:

* ``prompt`` — a plain ``str`` user turn (default, back-compat).
* ``content`` — a ``list[ContentBlock]`` for a single user turn with
  rich content (image, document, video, text).
* ``messages`` — a full ``list[Message]`` conversation.

Inside any nested ``source`` dict that lives within a content block
(``ImageSource``, ``DocumentSource``, ``VideoSource``, or any future
media block Strands adds), a JSON-safe synonym ``base64`` may carry the
binary payload; this module decodes it into the native ``bytes`` field
the Strands SDK expects.  ``location`` (S3) sources are passed through
untouched.
"""

from __future__ import annotations

import base64
import binascii
import json
import logging
from collections.abc import Mapping
from typing import Any

from strands.types.agent import AgentInput
from strands.types.content import ContentBlock, Message, Messages

logger = logging.getLogger(__name__)


class MultimodalPayloadError(ValueError):
    """Raised when an ``/invocations`` payload cannot be parsed.

    Subclass of :class:`ValueError` so existing callers that already
    handle ``ValueError`` continue to work.
    """


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def parse_payload(
    payload: Mapping[str, Any],
    *,
    max_payload_bytes: int | None,
    max_media_bytes: int,
    max_media_blocks: int,
) -> AgentInput:
    """Translate a JSON payload into a Strands :data:`AgentInput`.

    Args:
        payload: The decoded JSON request body.  Must contain exactly
            one of ``prompt`` / ``content`` / ``messages``.
        max_payload_bytes: Maximum length of the JSON-serialized
            payload in bytes, or ``None`` to disable the check.
        max_media_bytes: Maximum decoded size in bytes for any single
            ``source.base64`` block.
        max_media_blocks: Maximum number of media blocks (any
            ``source`` dict containing ``base64`` or ``location``)
            allowed across the whole payload.

    Returns:
        A ``str``, ``list[ContentBlock]`` or :data:`Messages` value
        suitable for ``entry.invoke_async``.

    Raises:
        MultimodalPayloadError: When the payload shape is invalid,
            mutually-exclusive keys collide, base64 is malformed, or
            a size/count limit is exceeded.
    """
    if not isinstance(payload, Mapping):
        raise MultimodalPayloadError("payload must be a JSON object")

    if max_payload_bytes is not None:
        try:
            encoded_size = len(json.dumps(payload, default=_json_default).encode("utf-8"))
        except (TypeError, ValueError) as exc:
            raise MultimodalPayloadError("payload is not JSON-serializable") from exc
        if encoded_size > max_payload_bytes:
            raise MultimodalPayloadError(
                "payload size %d bytes exceeds max_payload_bytes=%d"
                % (encoded_size, max_payload_bytes)
            )

    present = [key for key in ("prompt", "content", "messages") if key in payload]
    if not present:
        raise MultimodalPayloadError(
            "missing required field: one of 'prompt', 'content', or 'messages'"
        )
    if len(present) > 1:
        raise MultimodalPayloadError(
            "exactly one of 'prompt', 'content', 'messages' allowed, got %s" % ", ".join(present)
        )

    counter = _MediaCounter(max_media_bytes=max_media_bytes, max_media_blocks=max_media_blocks)
    key = present[0]

    if key == "prompt":
        return _parse_prompt(payload["prompt"])
    if key == "content":
        return _parse_content(payload["content"], counter)
    return _parse_messages(payload["messages"], counter)


def describe_input(agent_input: Any) -> str:
    """Return a short, log-safe description of an :data:`AgentInput`.

    Accepts ``Any`` so it can also be used on raw payload values
    before they have been validated.

    Never raises.  Truncates strings, and for structured inputs
    reports the type and block/message count instead of leaking
    binary content into log lines.

    Args:
        agent_input: Anything accepted by ``entry.invoke_async``.

    Returns:
        A short single-line ``str`` suitable for a log message.
    """
    if agent_input is None:
        return "None"
    if isinstance(agent_input, str):
        snippet = agent_input[:80]
        return "str:%r" % snippet
    if isinstance(agent_input, list):
        if not agent_input:
            return "list:empty"
        first = agent_input[0]
        if isinstance(first, dict) and "role" in first:
            return "messages:count=%d" % len(agent_input)
        return "content:count=%d" % len(agent_input)
    return "type=%s" % type(agent_input).__name__


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class _MediaCounter:
    """Tracks the number of media blocks decoded so far."""

    def __init__(self, *, max_media_bytes: int, max_media_blocks: int) -> None:
        self.max_media_bytes = max_media_bytes
        self.max_media_blocks = max_media_blocks
        self.count = 0

    def bump(self) -> None:
        """Increment the counter and raise if the cap is exceeded."""
        self.count += 1
        if self.count > self.max_media_blocks:
            raise MultimodalPayloadError(
                "media block count %d exceeds max_media_blocks=%d"
                % (self.count, self.max_media_blocks)
            )


def _parse_prompt(value: Any) -> str:
    """Validate a ``prompt`` value is a non-empty ``str``."""
    if not isinstance(value, str):
        raise MultimodalPayloadError("'prompt' must be a string")
    if not value:
        raise MultimodalPayloadError("'prompt' must not be empty")
    return value


def _parse_content(value: Any, counter: _MediaCounter) -> list[ContentBlock]:
    """Validate and decode a ``content`` block list."""
    if not isinstance(value, list) or not value:
        raise MultimodalPayloadError("'content' must be a non-empty list of content blocks")
    return [_decode_block(block, counter) for block in value]


def _parse_messages(value: Any, counter: _MediaCounter) -> Messages:
    """Validate and decode a full ``messages`` conversation."""
    if not isinstance(value, list) or not value:
        raise MultimodalPayloadError("'messages' must be a non-empty list of messages")
    return [_decode_message(message, counter) for message in value]


def _decode_message(message: Any, counter: _MediaCounter) -> Message:
    """Validate one message dict and decode any nested media blocks."""
    if not isinstance(message, dict):
        raise MultimodalPayloadError("each message must be a JSON object")
    role = message.get("role")
    if role not in ("user", "assistant"):
        raise MultimodalPayloadError("message 'role' must be 'user' or 'assistant', got %r" % role)
    content = message.get("content")
    if not isinstance(content, list) or not content:
        raise MultimodalPayloadError("message 'content' must be a non-empty list of blocks")
    decoded_blocks = [_decode_block(block, counter) for block in content]
    return {"role": role, "content": decoded_blocks}  # type: ignore[typeddict-item]


def _decode_block(block: Any, counter: _MediaCounter) -> ContentBlock:
    """Walk a content block and decode any nested ``source.base64`` fields."""
    if not isinstance(block, dict):
        raise MultimodalPayloadError("each content block must be a JSON object")
    return _walk(block, counter)  # type: ignore[return-value]


def _walk(value: Any, counter: _MediaCounter) -> Any:
    """Recursively rewrite ``source.base64`` into ``source.bytes``.

    Any nested dict literally named ``source`` containing ``base64``
    is treated as a Strands media source, regardless of which media
    block type wraps it.  This stays forward-compatible if Strands
    adds new media block types.
    """
    if isinstance(value, dict):
        return {key: _walk_field(key, sub, counter) for key, sub in value.items()}
    if isinstance(value, list):
        return [_walk(item, counter) for item in value]
    return value


def _walk_field(key: str, value: Any, counter: _MediaCounter) -> Any:
    """Apply source-decoding to a ``source`` field, otherwise recurse."""
    if key == "source" and isinstance(value, dict):
        return _decode_source(value, counter)
    return _walk(value, counter)


def _decode_source(source: Mapping[str, Any], counter: _MediaCounter) -> dict[str, Any]:
    """Decode a single ``source`` dict.

    * If ``base64`` is present, decode it into ``bytes`` and count it
      against the media-blocks cap.
    * If ``location`` is present, pass through (S3 references are
      tracked against the cap too).
    * Otherwise, leave the source untouched and recurse.

    Raises:
        MultimodalPayloadError: When both ``base64`` and ``bytes`` /
            ``location`` collide, base64 is malformed, or the decoded
            payload exceeds ``max_media_bytes``.
    """
    if "base64" in source:
        if "bytes" in source or "location" in source:
            raise MultimodalPayloadError(
                "source may set only one of 'base64', 'bytes', or 'location'"
            )
        encoded = source["base64"]
        if not isinstance(encoded, str):
            raise MultimodalPayloadError("source.base64 must be a string")
        try:
            decoded = base64.b64decode(encoded, validate=True)
        except (binascii.Error, ValueError) as exc:
            raise MultimodalPayloadError("source.base64 is not valid base64") from exc
        if len(decoded) > counter.max_media_bytes:
            raise MultimodalPayloadError(
                "media block size %d bytes exceeds max_media_bytes=%d"
                % (len(decoded), counter.max_media_bytes)
            )
        counter.bump()
        rewritten = {key: value for key, value in source.items() if key != "base64"}
        rewritten["bytes"] = decoded
        return rewritten

    if "location" in source:
        counter.bump()
        return dict(source)

    return {key: _walk(value, counter) for key, value in source.items()}


def _json_default(value: Any) -> Any:
    """Make ``bytes`` size-measurable when computing payload size."""
    if isinstance(value, (bytes, bytearray)):
        return base64.b64encode(value).decode("ascii")
    raise TypeError("object of type %s is not JSON-serializable" % type(value).__name__)
