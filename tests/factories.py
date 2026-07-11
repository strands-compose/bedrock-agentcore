"""Payload and data builders for tests.

Builders make relevant inputs visible and hide boilerplate. Provide both
raw dict builders (for parse_payload tests) and content-block builders
(for client tests).
"""

from __future__ import annotations

import base64
from typing import Any


def payload(prompt: str | dict[str, Any] | list[Any] = "Hello") -> dict[str, Any]:
    """A minimal valid invocation payload. Override prompt to test variants."""
    return {"prompt": prompt}


def image_payload(
    *,
    format: str = "png",
    data: bytes = b"\x89PNG\r\n\x1a\n" + b"\x00" * 100,
) -> dict[str, Any]:
    """A payload containing one image block with valid base64 source."""
    return {
        "prompt": [
            {
                "image": {
                    "format": format,
                    "source": {"base64": base64.b64encode(data).decode()},
                }
            }
        ]
    }


def document_payload(
    *,
    format: str = "pdf",
    name: str = "report",
    data: bytes = b"%PDF-1.4" + b"\x00" * 100,
) -> dict[str, Any]:
    """A payload containing one document block with valid base64 source."""
    return {
        "prompt": [
            {
                "document": {
                    "format": format,
                    "name": name,
                    "source": {"base64": base64.b64encode(data).decode()},
                }
            }
        ]
    }


def reply_payload(
    interrupt_id: str = "int-001",
    response: Any = "yes",
) -> dict[str, Any]:
    """A payload containing one reply block."""
    return {"prompt": [{"reply": {"interrupt_id": interrupt_id, "response": response}}]}


def text_block_payload(text: str = "Hello world") -> dict[str, Any]:
    """A payload containing one text block."""
    return {"prompt": [{"text": text}]}
