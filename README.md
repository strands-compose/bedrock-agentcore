<div align="center">

<img src="https://raw.githubusercontent.com/strands-compose/.github/main/img/bedrock-agentcore.png" alt="strands-compose-agentcore" width="600">

---

**Deploy [strands-compose](https://github.com/strands-compose/sdk-python) agent systems on [AWS Bedrock AgentCore Runtime](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/) — YAML in, managed cloud agents out**

<p>
  <a href="https://www.python.org/"><img src="https://img.shields.io/badge/python-3.11+-blue.svg" alt="Python 3.11+"></a>
  <a href="https://pypi.org/project/strands-compose-agentcore/"><img src="https://img.shields.io/pypi/v/strands-compose-agentcore.svg" alt="PyPI version"></a>
  <a href="https://github.com/strands-compose/sdk-python"><img src="https://img.shields.io/badge/strands--compose-0.2.0+-green.svg" alt="strands-compose"></a>
  <a href="LICENSE"><img src="https://img.shields.io/badge/license-Apache--2.0-blue.svg" alt="License"></a>
</p>

</div>

> [!IMPORTANT]
> Community project — not affiliated with AWS or the strands-agents team. Bugs here? [Open an issue](https://github.com/strands-compose/bedrock-agentcore/issues). Bugs in the underlying SDK? Head to [strands-agents](https://github.com/strands-agents/sdk-python).

## What is this?

You built your agent system with [strands-compose](https://github.com/strands-compose/sdk-python) — models, tools, orchestrations, all described in YAML. It works locally. Now you want it running on AWS with per-session isolation, auto-scaling, and zero infrastructure management.

**strands-compose-agentcore** fills the gap between strands-compose and [AWS Bedrock AgentCore Runtime](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/). It wraps your YAML config as the ASGI app that AgentCore expects, provides a CLI for local development with a built-in REPL, and ships a client for invoking deployed agents — from the terminal or from your own apps.

Same config you already have. Same agents. Test locally, deploy, invoke — all from the command line.

## See it in action

You have your strands-compose `config.yaml`. Here's how fast you go from zero to deployed:

**Create the app** — one function call wraps your config as a `BedrockAgentCoreApp`:

```python
# main.py
from pathlib import Path
from strands_compose_agentcore import create_app

app = create_app(Path(__file__).parent / "config.yaml")
```

**Run locally** — dev server + interactive REPL in one terminal:

```bash
sca dev --config config.yaml
```

**Deploy to AWS** — register and ship it to AgentCore Runtime:

```bash
agentcore add agent \
  --type byo \
  --name my_agent \
  --code-location my_agent \
  --entrypoint main.py \
  --language Python \
  --framework Strands \
  --model-provider Bedrock
agentcore deploy
```

**Invoke the deployed agent** — interactive REPL or programmatic client:

```bash
sca client remote --arn <ARN> --region us-west-2
```

Your `config.yaml` never changed. Your agents never changed. You just moved from laptop to managed cloud infrastructure.

## What this package gives you

### 🏭 `create_app()` — the core value

The real value of this package is a single factory function. AgentCore Runtime expects a specific ASGI app with `/invocations` and `/ping` endpoints, session-aware lifecycle management, event streaming, concurrency guards, and health reporting. `create_app()` handles all of that — you pass your YAML config and get a production-ready `BedrockAgentCoreApp` with zero knowledge of the runtime contract required:

```python
from strands_compose_agentcore import create_app
app = create_app("config.yaml")  # that's it
```

Without this factory, you'd need to manually wire `load_config`, `resolve_infra`, `load_session`, ASGI lifespan, MCP lifecycle, session caching, event queue plumbing, streaming serialization, and concurrency guards. `create_app()` does all of that in one call.

### 🛠️ CLI for strands-compose streaming events

The [AgentCore CLI](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/agentcore-cli.html) provides `create`, `add`, `deploy`, `status`, `logs`, and more — we recommend it and don't replace or abstract any of it.

strands-compose-agentcore CLI tools `dev` and `client` use `AnsiRenderer` from strands-compose to render stream events with color, formatting, and progressive typewriter output. This is the only reason we ship our own CLI — we don't duplicate or replace the AgentCore CLI, we complement it for the streaming use case it doesn't cover.

### 📡 A client for your apps

`AgentCoreClient` is an async boto3 wrapper that streams SSE events from deployed agents — embed it in FastAPI, Django, Lambda, or background workers. One client instance, safe for concurrent multi-tenant use, with typed errors and a dedicated thread pool.

## How you deploy

**For individual developers and small teams**, we recommend the [AgentCore CLI](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/agentcore-cli.html). It handles project scaffolding, packaging, and deployment in a few commands. Use `sca dev` for local iteration, `agentcore deploy` to ship.

**For enterprise teams**, you likely have your own infrastructure-as-code (Terraform, CDK, CloudFormation) and CI/CD pipelines. In that case, `create_app()` is all you need from this package — build a Docker image with your `main.py` and `config.yaml`, push it to ECR, and let your pipeline update the agent runtime. Or ship as a CodeZip artifact to S3. The AgentCore CLI is optional — it's a convenient tool, not a requirement.

See [Chapter 09 — Deployment Strategies](docs/Chapter_09.md) for a deep dive on both paths.

## How it works

```
┌─────────────────────────────────────────────────────────────┐
│  config.yaml                                                │  ← You write this
│  (models, agents, tools, orchestrations)                    │
├─────────────────────────────────────────────────────────────┤
│  strands-compose                                            │  ← Parses YAML,
│  (load_config, resolve_infra, load_session)                 │     resolves agents
├─────────────────────────────────────────────────────────────┤
│  strands-compose-agentcore       ◄── THIS PACKAGE           │  ← Wraps as ASGI app,
│  (app factory, CLI toolkit, AgentCoreClient)                │     CLI, client
├─────────────────────────────────────────────────────────────┤
│  AgentCore CLI + bedrock-agentcore SDK                      │  ← Project scaffold,
│  (agentcore create/deploy, BedrockAgentCoreApp)             │     deploy, ASGI server
├─────────────────────────────────────────────────────────────┤
│  AWS Bedrock AgentCore Runtime                              │  ← Managed compute
│  (per-session microVM, auto-scaling, CloudWatch)            │     (you deploy here)
└─────────────────────────────────────────────────────────────┘
```

Each layer does one thing. strands-compose parses your YAML and builds agents. This package wraps them as an ASGI app and provides the CLI glue. The AgentCore CLI and SDK handle project scaffolding, deployment, and the `/invocations` wire protocol. AgentCore Runtime runs it all on managed infrastructure. You only touch the top two layers.

## Getting started

### Install

```bash
pip install strands-compose-agentcore
```

> This pulls in `strands-compose` and `bedrock-agentcore` automatically. The [AgentCore CLI](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/agentcore-cli.html) is a separate Node.js tool: `npm install -g @aws/agentcore`

### Required files

Every agent needs three files:

**`config.yaml`** — your strands-compose agent definition:

```yaml
models:
  default:
    provider: bedrock
    model_id: openai.gpt-oss-20b-1:0

agents:
  assistant:
    model: default
    system_prompt: "You are a helpful assistant."

entry: assistant
```

**`main.py`** — the entry script:

```python
from pathlib import Path
from strands_compose_agentcore import create_app

app = create_app(Path(__file__).parent / "config.yaml")
```

**`pyproject.toml`** — declares dependencies for deployment:

```toml
[project]
name = "my-agent"
requires-python = ">=3.11"
dependencies = [
    "strands-compose-agentcore",
]
```

### The full workflow

```bash
# 1. Create an AgentCore project (AgentCore CLI)
agentcore create --name project --no-agent
cd project

# 2. Create your agent files (main.py, config.yaml, pyproject.toml)
mkdir my_agent
# → Add the three files shown above to my_agent/

# 3. Test locally (dev server + REPL in one terminal)
sca dev --config my_agent/config.yaml

# 4. Register the agent and deploy to AWS
agentcore add agent \
  --type byo \
  --name my_agent \
  --code-location my_agent \
  --entrypoint main.py \
  --language Python \
  --framework Strands \
  --model-provider Bedrock
agentcore deploy

# 5. Connect to the live agent
sca client remote --arn <ARN> --region us-west-2
```

That's the entire journey — from an empty directory to a deployed, production-ready agent system. The `dev` command runs the exact same ASGI app that will run in production, so what works locally works deployed.

## The CLI toolkit

| Command | What it does |
|---------|-------------|
| `dev` | Start the ASGI server + interactive REPL in one terminal — iterate without leaving the shell |
| `client local` | Connect a REPL to a local dev server |
| `client remote` | Connect a REPL to a deployed agent on AgentCore Runtime |

## Examples

Every example is self-contained with a `README.md` and everything you need to run it:

| # | Example | What you'll learn |
|---|---------|-------------------|
| 01 | [Quick Start](examples/01_quick_start/README.md) | Multi-agent orchestration with tools and the `dev` CLI — run and test locally |
| 02 | [Deploy](examples/02_deploy/README.md) | End-to-end deployment: create files → test → deploy → connect remotely |

```bash
# Try the quick start example right now
sca dev --config examples/01_quick_start/config.yaml
```

## Documentation

Deep dives into every component — architecture, API reference, deployment patterns, and advanced topics:

| Chapter | What it covers |
|---------|----------------|
| [01 — What Is This?](docs/Chapter_01.md) | The problem, the solution, the tech stack |
| [02 — Getting Started](docs/Chapter_02.md) | Install, configure, run your first agent |
| [03 — The App Factory](docs/Chapter_03.md) | `create_app()` deep dive |
| [04 — Session & Streaming](docs/Chapter_04.md) | Per-session lifecycle, event queues, SSE wire protocol |
| [05 — The CLI](docs/Chapter_05.md) | Every command, every flag, explained |
| [06 — Deployment](docs/Chapter_06.md) | CodeZip and container paths to AgentCore Runtime |
| [07 — The Client](docs/Chapter_07.md) | `AgentCoreClient` and `LocalClient` API + integration patterns |
| [08 — Advanced Topics](docs/Chapter_08.md) | VPC, logging, timeouts, health checks, CDK |
| [09 — Deployment Strategies](docs/Chapter_09.md) | Individual developers vs enterprise teams — AgentCore CLI, IaC, CI/CD |
| [Quick Recipes](docs/Quick_Recipes.md) | AWS services reference — tools, packages, and patterns at a glance |

## Developer setup

```bash
git clone https://github.com/strands-compose/bedrock-agentcore
cd bedrock-agentcore
uv run just install      # install deps + wire git hooks (run once after clone)

uv run just check        # lint + type check + security scan
uv run just test         # pytest with coverage
uv run just format       # auto-format (Ruff)
```

> Re-install hooks after a fresh clone or if hooks stop running: `uv run just install-hooks`

See [CONTRIBUTING.md](CONTRIBUTING.md) for the full contribution guide, [AGENTS.md](AGENTS.md) for coding standards, and [CHANGELOG.md](CHANGELOG.md) for release history.

---

## License

Apache-2.0 — see [LICENSE](LICENSE).
