# 01 — Quick Start

> Write a YAML config. Run one command. Talk to your agents.

## What this shows

- A multi-agent delegate orchestration — coordinator, researcher, and writer
- `sca dev` — start a server and open a REPL in one command
- How `mode: delegate` routes work between agents
- Real-time streaming of all events (tokens, handoffs) via SSE

## Files

| File | Purpose |
|------|---------|
| `config.yaml` | Multi-agent config: coordinator delegates to researcher and writer |
| `main.py` | Entry script — wraps config as a `BedrockAgentCoreApp` |

## Prerequisites

- AWS credentials configured (`aws configure` or environment variables)
- Bedrock model access enabled in the [Bedrock console](https://console.aws.amazon.com/bedrock/)
- Dependencies installed: `pip install strands-compose-agentcore`

## Run

From the project root:

```bash
# Option A: dev CLI (recommended — starts server + REPL together)
sca dev --config examples/01_quick_start/config.yaml

# Option B: standalone server + separate REPL
python examples/01_quick_start/main.py
# In another terminal:
sca client local
```

Type a message and press Enter to talk to your agent.

## How it works

The config wires three agents through a delegate orchestration:

```
coordinator  (entry via orchestration)
  ├── researcher — gathers facts on a topic
  └── writer     — produces a polished report from research
```

The `coordinator` is the entry point. For every task it receives, it delegates to `researcher` to gather facts, then passes those to `writer` for the final output. All agent events stream back in real-time.

`main.py` is a single function call:

```python
from pathlib import Path
from strands_compose_agentcore import create_app

app = create_app(Path(__file__).parent / "config.yaml")
```

The module-level `app` variable is what AgentCore Runtime discovers at deploy time.

## Good to know

- **Session state persists** within a dev session. Follow-up messages continue the conversation.
- Change `model_id` in `config.yaml` to use a different Bedrock model.
- The `description` on each agent tells the coordinator what each sub-agent is for — keep them accurate.

## REPL commands

| Command | Action |
|---------|--------|
| `/help` | Show available commands |
| `/clear` | Clear the screen |
| `/session` | Show current session ID |
| `/exit` | Exit the REPL |

## Try these prompts

- `Research the history of Python and write a report`
- `Give me a briefing on large language models`

## Next

Ready to deploy? See [02_deploy](../02_deploy/README.md) for the full deployment walkthrough — including `pyproject.toml` and the `agentcore` CLI.
