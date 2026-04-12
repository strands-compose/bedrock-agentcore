# 02 — Deploy to AgentCore Runtime

> From zero to a deployed agent in five steps.

This example walks through the complete deployment journey:
create your agent files, test locally, deploy to AWS, and connect remotely.

This directory contains the three files every deployable agent needs — use them as a starting point or reference.

## Files

| File | Purpose |
|------|---------|
| `config.yaml` | Minimal strands-compose YAML config — one model, one agent |
| `main.py` | Entry script — exposes a module-level `app` variable for AgentCore Runtime |
| `pyproject.toml` | Python project file — declares `strands-compose-agentcore` as a dependency |

---

## Prerequisites

- **AWS credentials** configured (`aws configure` or environment variables)
- **Bedrock model access** enabled in the [Bedrock console](https://console.aws.amazon.com/bedrock/)
- **AgentCore CLI** installed: `npm install -g @aws/agentcore` (requires Node.js 20+)
  — see [AgentCore CLI docs](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/agentcore-cli.html)
  and [AgentCore CLI GitHub](https://github.com/aws/agentcore-cli)
- **strands-compose-agentcore** installed: `pip install strands-compose-agentcore`

---

## Step 1 — Create the AgentCore project

The AgentCore CLI manages deployment scaffolding. Create a project:

```bash
agentcore create --name project --no-agent
cd project
```

This creates a directory with the AgentCore project structure:

```
project/
└── agentcore/
    ├── agentcore.json      # Project config (agents, build settings)
    └── aws-targets.json    # AWS account + region (populated on first deploy)
```

**Key options:**

| Flag | Purpose |
|------|---------|
| `--name <name>` | Project name (alphanumeric, max 23 chars) |
| `--no-agent` | Skip the interactive agent wizard — we add our own |
| `--build <type>` | `CodeZip` (default) or `Container` |

> For full `agentcore create` options, see the [AgentCore CLI reference](https://github.com/aws/agentcore-cli/blob/main/docs/commands.md).

---

## Step 2 — Create your agent files

Create a directory for your agent inside the project:

```bash
mkdir my_agent
```

Add three files to it:

**`my_agent/main.py`** — wraps your config as a `BedrockAgentCoreApp`:

```python
from pathlib import Path
from strands_compose_agentcore import create_app

app = create_app(Path(__file__).parent / "config.yaml")

if __name__ == "__main__":
    app.run(port=8080)
```

**`my_agent/config.yaml`** — your agent definition:

```yaml
models:
  default:
    provider: bedrock
    model_id: openai.gpt-oss-20b-1:0

agents:
  assistant:
    model: default
    system_prompt: "You are a helpful assistant. Keep answers clear and concise."

entry: assistant
```

**`my_agent/pyproject.toml`** — declares the dependency for deployment:

```toml
[project]
name = "my-agent"
version = "0.1.0"
requires-python = ">=3.11"
dependencies = [
    "strands-compose-agentcore",
]
```

**What each file does:**

- **`config.yaml`** — defines your agents, tools, and orchestrations. All YAML options are defined by [strands-compose](https://github.com/strands-compose/sdk-python).
- **`main.py`** — calls `create_app(config.yaml)` and exposes a module-level `app` variable.
- **`pyproject.toml`** — declares `strands-compose-agentcore` as a dependency. The AgentCore CLI reads this to install dependencies during staging.

After this step your project should look like this:

```
project/
├── agentcore/
│   ├── agentcore.json
│   └── aws-targets.json
└── my_agent/
    ├── config.yaml
    ├── main.py
    └── pyproject.toml
```

Edit `config.yaml` to define your agents. See [01_quick_start](../01_quick_start/README.md) for a minimal working example.

---

## Step 3 — Test locally

Run the dev server and REPL:

```bash
cd ..
# Your cwd should be project/
sca dev --config ./my_agent/config.yaml
```

This starts an HTTP server on port 8080 and opens an interactive REPL. Test your agent, iterate on the config, and verify everything works before deploying.

**Key options:**

| Flag | Default | Purpose |
|------|---------|---------|
| `--config <path>` | `./config.yaml` | Path to strands-compose YAML config |
| `--port <number>` | `8080` | HTTP server port |
| `--session-id <id>` | auto-generated | Session ID for the REPL |

> **Tip:** The dev server runs the exact same `BedrockAgentCoreApp` that will run in production. What works locally will work deployed.

---

## Step 4 — Register and deploy

### Register the agent

Use `agentcore add agent` to register the agent in the AgentCore project:

```bash
# Your cwd should be project/
agentcore add agent \
  --type byo \
  --name my_agent \
  --code-location my_agent \
  --entrypoint main.py \
  --language Python \
  --framework Strands \
  --model-provider Bedrock
```

This updates `agentcore/agentcore.json` with the agent configuration.

**A note on the flags:**

- `--type byo` — **bring-your-own** runtime. The agent is fully self-contained; AgentCore Runtime just invokes it.
- `--language`, `--framework`, `--model-provider` — **required by the CLI for `byo` type, but not used at runtime.** For `byo` agents the runtime doesn't enforce a particular language or framework — you own the entire execution. These flags are a CLI validation artefact and may become optional in a future release.
- `--entrypoint main.py` — the file AgentCore Runtime loads to find the `app` variable. `main.py` is the CLI default and the convention we follow here, but you can use any filename as long as you pass the correct value to `--entrypoint`.

**Useful extras:**

| Flag | Purpose |
|------|---------|
| `--build <type>` | `CodeZip` (default, up to 250 MB) or `Container` |
| `--network-mode <mode>` | `PUBLIC` (default) or `VPC` |
| `--idle-timeout <seconds>` | Session idle timeout (60–28800, default: 900) |
| `--max-lifetime <seconds>` | Max session lifetime (60–28800) |

### Deploy

```bash
agentcore deploy
```

On the first deploy, the CLI:
1. Auto-detects your AWS account (via STS) and region
2. Saves them to `agentcore/aws-targets.json`
3. Installs dependencies from `pyproject.toml` into a staging directory
4. Copies your source code as-is
5. Packages everything as a zip (CodeZip) or Docker image (Container)
6. Creates a CloudFormation stack via CDK
7. Deploys the agent runtime

Subsequent deploys:

```bash
agentcore deploy -y       # auto-confirm (skip interactive prompts)
agentcore deploy --plan   # preview changes without deploying
agentcore deploy -y -v    # auto-confirm with verbose output
```

> **CI/scripted workflows:** The `-y` flag requires `aws-targets.json` to exist. Either run an interactive deploy first, or create it manually:
> ```json
> [{"name": "default", "account": "123456789012", "region": "us-west-2"}]
> ```

---

## Step 5 — Connect to the deployed agent

After deployment, check the agent status and get the ARN:

```bash
agentcore status
```

Connect with the interactive REPL:

```bash
sca client remote \
  --arn arn:aws:bedrock-agentcore:us-west-2:123456789012:runtime/project_my_agent-XXXXXXXXXX \
  --region us-west-2
```

> **Tip:** The ARN follows the pattern `{project}_{agent}-{randomSuffix}`. Get it from `agentcore status` output.

### Other useful commands

```bash
# View logs
agentcore logs --since 30m

# Remove all agents (marks for removal on next deploy)
agentcore remove all
agentcore deploy -y
```

---

## Complete workflow summary

```bash
# 1. Create project
agentcore create --name project --no-agent
cd project

# 2. Create agent files
mkdir my_agent
# → Add main.py, config.yaml, pyproject.toml to my_agent/

# 3. Edit config
#    → edit my_agent/config.yaml with your agents, tools, orchestrations

# 4. Test locally
sca dev --config my_agent/config.yaml

# 5. Register + deploy
agentcore add agent \
  --type byo \
  --name my_agent \
  --code-location my_agent \
  --entrypoint main.py \
  --language Python \
  --framework Strands \
  --model-provider Bedrock

agentcore deploy

# 6. Connect remotely
agentcore status
sca client remote --arn <ARN> --region <REGION>
```

## Next

For client integration patterns (Python client, CLI REPL, FastAPI), see [Chapter 07 (The Client)](../../docs/Chapter_07.md).

For advanced deployment topics (VPC, containers, CDK customization, observability), see the [docs](../../docs/README.md) — specifically [Chapter 06 (Deployment)](../../docs/Chapter_06.md) and [Chapter 08 (Advanced Topics)](../../docs/Chapter_08.md).
