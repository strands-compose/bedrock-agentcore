"""Entry script for the quick-start example.

Usage (local dev):
    sca dev --config examples/01_quick_start/config.yaml

Usage (standalone):
    python examples/01_quick_start/main.py
"""

from pathlib import Path

from strands_compose_agentcore import create_app

app = create_app(Path(__file__).parent / "config.yaml")

if __name__ == "__main__":
    app.run(port=8080)
