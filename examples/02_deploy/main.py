"""Entry script for deploying a strands-compose agent on AgentCore Runtime.

Usage (local dev):
    sca dev --config examples/02_deploy/config.yaml

Usage (standalone):
    python examples/02_deploy/main.py

The module-level ``app`` variable is what AgentCore Runtime discovers
at deploy time. The ``if __name__`` block lets you run the server locally.
"""

from pathlib import Path

from strands_compose_agentcore import create_app

app = create_app(Path(__file__).parent / "config.yaml")

if __name__ == "__main__":
    app.run(port=8080)
