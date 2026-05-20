"""Entry script for the multimodal example.

Usage (local dev):
    In first terminal run local server:
    python examples/03_multimodal/main.py

    In second terminal run client:
    python examples/03_multimodal/client.py "What is in this image?"
"""

from pathlib import Path

from strands_compose_agentcore import create_app

app = create_app(Path(__file__).parent / "config.yaml")

if __name__ == "__main__":
    app.run(port=8080)
