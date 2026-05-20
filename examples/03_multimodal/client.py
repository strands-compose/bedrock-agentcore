"""Send an image plus a text question to the multimodal agent.

Usage::

    python examples/03_multimodal/client.py path/to/image.png "What is this?"

The local server must already be running (``python main.py`` or
``sca dev --config examples/03_multimodal/config.yaml``).
"""

from __future__ import annotations

import sys
from pathlib import Path

from strands_compose_agentcore import LocalClient, image_block


def main() -> int:
    if len(sys.argv) < 3:
        print("usage: client.py <image_path> <question>", file=sys.stderr)
        return 2

    image_path = Path(sys.argv[1])
    question = sys.argv[2]

    client = LocalClient()
    blocks = [image_block(image_path), {"text": question}]

    for event in client.invoke(content=blocks):
        print(event.type, event.data)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
