"""Entry script for the multimodal example.

Usage (local dev):
    sca dev --config examples/03_multimodal/config.yaml

Then in another terminal, run ``client.py`` to send an image.
"""

from pathlib import Path

from strands_compose_agentcore import create_app

app = create_app(Path(__file__).parent / "config.yaml")

if __name__ == "__main__":
    app.run(port=8080)
