"""Send an image plus a text question to the multimodal agent.

Usage::
    In first terminal run local server:
    python examples/03_multimodal/main.py

    In second terminal run client:
    python examples/03_multimodal/client.py "What is in this image and document?"
"""

from __future__ import annotations

import sys
from pathlib import Path

from strands_compose_agentcore import ContentBlock, LocalClient, document, image, text


def main() -> int:
    # Check that the user provided a prompt as a command-line argument.
    if len(sys.argv) != 2:
        print("\nProvide prompt: python client.py <prompt>\n", file=sys.stderr)
        return 1

    prompt = sys.argv[1]
    image_path = Path(__file__).parent / "image.jpeg"
    doc_path = Path(__file__).parent / "doc.pdf"

    client = LocalClient()
    agent_input: list[ContentBlock] = [image(image_path), text(prompt), document(doc_path)]

    print("-" * 52)
    for event in client.invoke(agent_input):
        # Only print token events in this example, for a clean output
        if event.type == "token":
            print(event.data.get("text"), end="", flush=True)
        elif event.type == "error":
            print("\nError:", event.data.get("text"), file=sys.stderr)
        elif event.type == "agent_complete":
            usage = event.data.get("usage", {})
            # With caching on, cached prompt tokens are not counted in input_tokens.
            print(
                f"\n\n[USAGE] Input: {usage.get('input_tokens')} tokens"
                f" (+ cache read {usage.get('cache_read_input_tokens', 0)},"
                f" cache write {usage.get('cache_write_input_tokens', 0)}),"
                f"  Output: {usage.get('output_tokens')} tokens\n"
            )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
