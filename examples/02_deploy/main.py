"""Entry script for deploying a strands-compose agent on AgentCore Runtime.

Usage (local dev):
    sca dev --config examples/02_deploy/config.yaml

Usage (standalone):
    python examples/02_deploy/main.py

AgentCore Runtime runs this file as a script, so the ``if __name__``
block starts the server both locally and in the deployed runtime.
"""

from pathlib import Path

from strands_compose_agentcore import create_app

app = create_app(Path(__file__).parent / "config.yaml")

if __name__ == "__main__":
    app.run(port=8080)
