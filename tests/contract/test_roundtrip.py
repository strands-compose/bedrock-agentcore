"""The wire round-trip -- the drift guard between client and server.

A content block built by the client media builders survives
``build_invocation_body`` (client) and ``parse_payload`` (server) and lands
in the expected Strands runtime shape.  This is the single test that actually
catches client/server contract drift, so each block kind gets its own case.
"""

from __future__ import annotations

from typing import Any, cast

from strands_compose_agentcore import document, image, reply, text
from strands_compose_agentcore.client.utils import build_invocation_body
from strands_compose_agentcore.payload import parse_payload
from tests.factories import LIMITS


def _first_block(result: Any) -> dict[str, Any]:
    """Narrow parse_payload's polymorphic result to the first block dict."""
    assert isinstance(result, list)
    return cast(dict, result[0])


def test_text_block_round_trips_to_strands_text() -> None:
    body = build_invocation_body([text("hello")])
    result = parse_payload(body, **LIMITS)
    assert result == [{"text": "hello"}]


def test_image_block_round_trips_base64_to_bytes() -> None:
    raw = b"\x89PNG\r\n\x1a\n" + b"\x00" * 16
    body = build_invocation_body([image(raw, format="png")])
    block = _first_block(parse_payload(body, **LIMITS))
    assert block["image"]["format"] == "png"
    assert block["image"]["source"]["bytes"] == raw


def test_document_block_round_trips_base64_to_bytes() -> None:
    raw = b"%PDF-1.4" + b"\x00" * 16
    body = build_invocation_body([document(raw, format="pdf", name="report")])
    block = _first_block(parse_payload(body, **LIMITS))
    assert block["document"]["format"] == "pdf"
    assert block["document"]["name"] == "report"
    assert block["document"]["source"]["bytes"] == raw


def test_reply_block_round_trips_to_interrupt_response() -> None:
    body = build_invocation_body([reply("int-1", "yes")])
    result = parse_payload(body, **LIMITS)
    assert result == [{"interruptResponse": {"interruptId": "int-1", "response": "yes"}}]
