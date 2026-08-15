# Chapter 01 — What Is This?

## The Problem

You have a [strands-compose](https://github.com/strands-compose/sdk-python) YAML config that defines agents, models, tools, and orchestrations. You want to deploy those agents to [AWS Bedrock AgentCore Runtime](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/) — AWS's managed compute service for running AI agents — without rewriting your agent logic.

## The Solution

**strands-compose-agentcore** is a thin deployment adapter. It takes your strands-compose YAML config and wraps it as a `BedrockAgentCoreApp` — the ASGI server that [AgentCore Runtime](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/) expects.

```
Your YAML config → strands-compose (resolve) → strands-compose-agentcore (wrap) → AgentCore Runtime
```

The package provides two components:

1. **`create_app()`** — a factory function that turns your YAML config into an ASGI server compatible with AgentCore Runtime. Use this in your entry script.

2. **A CLI toolkit** — `dev` and `client` commands for local development and interactive testing.

## What It Is NOT

This package does **not**:

- **Define agents, models, or tools** — that's [strands-compose](https://github.com/strands-compose/sdk-python). We read the YAML config it defines; all agent logic lives there.
- **Provide the ASGI server or `/invocations` endpoint** — that's [bedrock-agentcore](https://pypi.org/project/bedrock-agentcore/) (the Python runtime SDK). We return a `BedrockAgentCoreApp` instance from it.
- **Deploy infrastructure** — that's the [AgentCore CLI](https://github.com/aws/agentcore-cli) ([docs](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/agentcore-cli.html)) or [AWS CDK](https://docs.aws.amazon.com/cdk/v2/guide/home.html). We provide convenience CLI for local testing and invoking deployed agents.
- **Manage the model runtime** — that's [Amazon Bedrock](https://docs.aws.amazon.com/bedrock/latest/userguide/). We configure which model to use; Bedrock handles inference.

We are the glue between strands-compose and AgentCore Runtime. Nothing more.

## Who Is This For?

- **strands-compose users** who want to deploy their YAML-defined agents to a managed AWS service
- **Teams** that want one-command local development (`sca dev`) and one-command deployment (`agentcore deploy`)
- **Application developers** who need to invoke deployed agents from their own code (FastAPI, Lambda, etc.)

## The Tech Stack

```
┌──────────────────────────────────────────┐
│  Your YAML Config (config.yaml)          │  ← You write this
├──────────────────────────────────────────┤
│  strands-compose                         │  ← Parses YAML, resolves agents
│  (load_config, load, EventQueue)         │
├──────────────────────────────────────────┤
│  strands-compose-agentcore  ← THIS PKG   │  ← Wraps as AgentCore app,
│  (create_app,                            │     dev server, client
│   AgentCoreClient, CLI)                  │
├──────────────────────────────────────────┤
│  bedrock-agentcore (pip)                 │  ← ASGI server, /invocations,
│  (BedrockAgentCoreApp,                   │     /ping, session context
│   BedrockAgentCoreContext)               │
├──────────────────────────────────────────┤
│  AgentCore CLI (npm)                     │  ← Scaffold, package, deploy,
│  (agentcore create, deploy, status,      │     logs, status, invoke
│   invoke, logs, dev)                     │
├──────────────────────────────────────────┤
│  AWS Bedrock AgentCore Runtime           │  ← Managed compute (microVM
│                                          │     per session, auto-scaling)
└──────────────────────────────────────────┘
```

| Component | Role | Install |
|-----------|------|---------|
| [strands-compose](https://github.com/strands-compose/sdk-python) | YAML → agent definitions | Transitive dependency |
| [bedrock-agentcore](https://pypi.org/project/bedrock-agentcore/) | ASGI server + session context | Transitive dependency |
| **strands-compose-agentcore** | Deployment adapter (this package) | `pip install strands-compose-agentcore` |
| [AgentCore CLI](https://github.com/aws/agentcore-cli) ([docs](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/agentcore-cli.html)) | Scaffold, deploy, logs, status | `npm install -g @aws/agentcore` |
| [boto3](https://pypi.org/project/boto3/) | Data-plane API (invoke) | For `AgentCoreClient` |

Installing `strands-compose-agentcore` pulls in `strands-compose` and `bedrock-agentcore` automatically. The [AgentCore CLI](https://github.com/aws/agentcore-cli) is a separate Node.js tool — you only need it for deployment.

## Architecture at a Glance

Config is parsed at boot; everything live is built on the first request:

1. **Config phase** (once at boot) — parse and validate the YAML into an `AppConfig`
2. **Session phase** (once per session ID) — build models, MCP clients, agents, orchestrations, wire event queues, set entry point

Why the split:
- A malformed config should fail before the server starts, not on a user's prompt
- Agents need a session ID for conversation history, and it only arrives with the first request
- [AgentCore Runtime](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/) allocates one microVM per session, so a session's objects live exactly as long as the pod

```
                    Boot                          First /invocations
                     │                                   │
                     ▼                                   ▼
            ┌─────────────────┐              ┌────────────────────┐
            │  load_config()  │              │  load(cfg, sid=…)  │
            │                 │              │  make_event_queue()│
            └────────┬────────┘              └─────────┬──────────┘
                     │                                 │
                 AppConfig                      Session State
              (pure data, no                (built on 1st request)
               live objects)                 • models
                                            • MCP clients
                                            • agents
                                            • orchestrations
                                            • session managers
                                            • entry point
                                            • event queue
```

## Minimal Example

```python
# main.py
from pathlib import Path
from strands_compose_agentcore import create_app

app = create_app(Path(__file__).parent / "config.yaml")

if __name__ == "__main__":
    app.run(port=8080)
```

That's 4 lines. The YAML config defines the agents; this script just wires them to the runtime.

## Next

[Chapter 02 — Getting Started](Chapter_02.md)
