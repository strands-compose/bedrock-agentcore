# Chapter 06 — Deployment

This chapter walks through deploying a strands-compose agent to [AWS Bedrock AgentCore Runtime](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/).

## Prerequisites

- **AWS account** with [Bedrock model access](https://console.aws.amazon.com/bedrock/home#/modelaccess) enabled
- **AWS credentials** configured (`aws configure` or environment variables)
- **strands-compose-agentcore** — `pip install strands-compose-agentcore`

Additional prerequisites depend on the deployment path you choose (see below).

## Required Files

Every deployable agent needs three files:

| File | Purpose |
|------|---------|
| `config.yaml` | strands-compose YAML config — defines models, agents, tools, orchestrations |
| `main.py` | Python entry script — exposes a module-level `app` variable |
| `pyproject.toml` | Python project file — declares `strands-compose-agentcore` as a dependency |

### `main.py`

```python
from pathlib import Path
from strands_compose_agentcore import create_app

app = create_app(Path(__file__).parent / "config.yaml")

if __name__ == "__main__":
    app.run(port=8080)
```

The module-level `app` variable is what AgentCore Runtime discovers at deploy time. The `if __name__` block lets you run the server locally with `python main.py`.

### `config.yaml`

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

All YAML options are defined by [strands-compose](https://github.com/strands-compose/sdk-python).

### `pyproject.toml`

```toml
[project]
name = "my-agent"
requires-python = ">=3.11"
dependencies = [
    "strands-compose-agentcore",
]
```

The AgentCore CLI reads this file to install dependencies during deployment. Only `name`, `requires-python`, and `dependencies` are required.

## Three Deployment Paths

| Path | Tooling | Build | Best for |
|------|---------|-------|----------|
| **A — CLI + CodeZip** | [AgentCore CLI](https://github.com/aws/agentcore-cli) | Code zip uploaded to S3 | Most users — one command, no Docker needed |
| **B — CLI + Container** | AgentCore CLI + Docker | Container image built via [CodeBuild](https://docs.aws.amazon.com/codebuild/) | Custom system deps, native libraries, ML models |
| **C — Manual Container** | Docker + [ECR](https://docs.aws.amazon.com/ecr/) + AWS CLI | Container image you build and push | Full control, no AgentCore CLI needed |

All three paths deploy the same `main.py` entry script to the same AgentCore Runtime — only the packaging and deployment mechanism differs.

### Build Type Comparison

| | CodeZip (Paths A) | Container (Paths B, C) |
|---|---------|-----------|
| **Max artifact size** | 250 MB | 1 GB |
| **Max sessions/s** | 25 | 0.16 |
| **Custom system deps** | No | Yes |
| **Docker required locally** | No | Path B: optional; Path C: yes |
| **Best for** | Most Python agents | Custom native libraries, ML models |

---

## Path A — CLI + CodeZip

The [AgentCore CLI](https://github.com/aws/agentcore-cli) handles the entire pipeline: validate, package as a zip, CDK synth, and CloudFormation deploy. This is the recommended approach for most users.

**Additional prerequisites:** [AgentCore CLI](https://github.com/aws/agentcore-cli) — `npm install -g @aws/agentcore` (requires Node.js 20+)

### 1. Create your agent files

Create a directory with the three required files:

```
my_agent/
├── config.yaml
├── main.py
└── pyproject.toml
```

See [Required Files](#required-files) for contents.

### 2. Test locally

```bash
sca dev --config my_agent/config.yaml
```

Verify your agent works before deploying.

### 3. Create an AgentCore project

```bash
agentcore create --name project --no-agent
cd project
```

This creates an AgentCore project structure. The `--no-agent` flag skips the interactive agent wizard since we register our own agent in the next step.

```
project/
└── agentcore/
    ├── agentcore.json
    └── aws-targets.json
```

### 4. Register your agent

Copy your agent files into the project and register them:

```bash
cp -r ../my_agent .

agentcore add agent \
  --type byo \
  --name my_agent \
  --code-location my_agent \
  --entrypoint main.py \
  --language Python \
  --framework Strands \
  --model-provider Bedrock
```

This updates `agentcore/agentcore.json` with the agent specification:

```json
{
  "name": "my_agent",
  "build": "CodeZip",
  "entrypoint": "main.py",
  "codeLocation": "app/my_agent/",
  "runtimeVersion": "PYTHON_3_13",
  "networkMode": "PUBLIC",
  "protocol": "HTTP"
}
```

**A note on the flags:**

- `--type byo` — **bring-your-own** runtime. The agent is fully self-contained; AgentCore Runtime just invokes it.
- `--language Python`, `--framework Strands`, `--model-provider Bedrock` — required by the CLI validation for HTTP protocol agents, but not used at runtime for BYO agents. The runtime doesn't enforce a particular language or framework — you own the entire execution.
- `--entrypoint main.py` — the file AgentCore Runtime loads to find the `app` variable. This is the CLI default, but you can use any filename.

### 5. Deploy

```bash
agentcore deploy
```

On the first deploy, the interactive TUI auto-detects your AWS account and region, installs dependencies from `pyproject.toml` into a staging directory, copies your source code, packages everything as a zip, and creates a CloudFormation stack. Subsequent deploys:

```bash
agentcore deploy -y       # auto-confirm (skip interactive prompts)
agentcore deploy --plan   # preview changes without deploying
agentcore deploy --diff   # show CDK diff without deploying
```

> **CI/scripted workflows:** The `-y` flag requires `agentcore/aws-targets.json` to exist. Either run an interactive deploy first, or create it manually:
> ```json
> [{"name": "default", "account": "123456789012", "region": "us-west-2"}]
> ```

### 6. Test the deployed agent

```bash
agentcore status
sca client remote \
  --arn arn:aws:bedrock-agentcore:us-west-2:123456789012:runtime/project_my_agent-XXXXXXXXXX
```

The ARN follows the pattern `{project}_{agent}-{randomSuffix}`. Get it from `agentcore status` output.

### How the CLI Packages Your Code (CodeZip)

The CLI takes your code as-is, installs dependencies, and ships it. It does not wrap, modify, or inject anything.

The CLI runs `uv pip install --target <staging> -r pyproject.toml`, copies everything from `--code-location` into the staging directory (excluding `agentcore`, `.git`, `.venv`, `__pycache__`, `.pytest_cache`, `.DS_Store`, `node_modules`), and packs it into a zip (max 250 MB). The zip is uploaded to S3 by CloudFormation.

Your `main.py`, `config.yaml`, and all source files land in the runtime exactly as they are in your `--code-location` directory.

---

## Path B — CLI + Container

Use this path when you need system-level dependencies, custom native libraries, or an artifact larger than 250 MB. The AgentCore CLI manages the deployment pipeline, but the agent is packaged as a Docker container image instead of a zip.

**Additional prerequisites:**

- [AgentCore CLI](https://github.com/aws/agentcore-cli) — `npm install -g @aws/agentcore`
- A container runtime is **not** required for `agentcore deploy` — [AWS CodeBuild](https://docs.aws.amazon.com/codebuild/) builds the image remotely. Supported runtimes: [Docker](https://docker.com), [Podman](https://podman.io), [Finch](https://runfinch.com).

### 1. Create your agent files

Same three files as Path A:

```
my_agent/
├── config.yaml
├── main.py
└── pyproject.toml
```

See [Required Files](#required-files) for contents.

### 2. Test locally

```bash
sca dev --config my_agent/config.yaml
```

### 3. Create an AgentCore project

```bash
agentcore create --name project --no-agent
cd project
```

### 4. Register your agent with Container build

```bash
cp -r ../my_agent .

agentcore add agent \
  --type byo \
  --name my_agent \
  --build Container \
  --code-location my_agent \
  --entrypoint main.py \
  --language Python \
  --framework Strands \
  --model-provider Bedrock
```

The `--build Container` flag tells the CLI to package your agent as a container image instead of a zip. The CLI generates a `Dockerfile` and `.dockerignore` in the agent's code directory:

```
my_agent/
├── .dockerignore        # generated by CLI
├── config.yaml
├── Dockerfile           # generated by CLI
├── main.py
└── pyproject.toml
```

The generated Dockerfile uses `ghcr.io/astral-sh/uv:python3.12-bookworm-slim` as the base image, creates a non-root `bedrock_agentcore` user (UID 1000), and runs the agent with `opentelemetry-instrument`. You can customize it freely — add system packages, change the base image, or use multi-stage builds.

`agentcore/agentcore.json` is updated with `"build": "Container"`:

```json
{
  "name": "my_agent",
  "build": "Container",
  "entrypoint": "main.py",
  "codeLocation": "app/my_agent/",
  "runtimeVersion": "PYTHON_3_13",
  "networkMode": "PUBLIC",
  "protocol": "HTTP"
}
```

### 5. Deploy

```bash
agentcore deploy -y
```

The CLI uses [AWS CodeBuild](https://docs.aws.amazon.com/codebuild/) to build the container image remotely and push it to ECR. No local Docker runtime is required for deployment.

If a local container runtime is available, running `agentcore package` beforehand validates the image builds correctly and stays under the 1 GB limit.

### 6. Test the deployed agent

Same as Path A:

```bash
agentcore status
sca client remote \
  --arn arn:aws:bedrock-agentcore:us-west-2:123456789012:runtime/project_my_agent-XXXXXXXXXX
```

---

## Path C — Manual Container Deployment

Build a Docker image, push it to [ECR](https://docs.aws.amazon.com/ecr/), and create the agent runtime with the AWS CLI. This path works without the AgentCore CLI and gives you full control over the build and deploy pipeline.

**Additional prerequisites:**

- [Docker](https://docker.com) (or another container runtime)
- [AWS CLI](https://docs.aws.amazon.com/cli/)

### Container Requirements

AgentCore Runtime imposes specific constraints on containers:

- **ARM64** — the runtime runs on [Graviton](https://aws.amazon.com/ec2/graviton/)
- **Port 8080** — the runtime expects the HTTP server on this port (8000 for MCP, 9000 for A2A)
- **Non-root user** — required by the runtime for security
- **Max 1 GB** — container image size limit
- **`POST /invocations`** and **`GET /ping`** — the two endpoints the runtime calls, both handled by `BedrockAgentCoreApp`

### 1. Create your agent files

Same three files as the other paths:

```
my_agent/
├── config.yaml
├── main.py
└── pyproject.toml
```

See [Required Files](#required-files) for contents.

### 2. Write the Dockerfile

Create `my_agent/Dockerfile`:

```dockerfile
# --- Stage 1: build dependencies ---
FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim AS builder

WORKDIR /app

ENV UV_COMPILE_BYTECODE=1 \
    UV_NO_PROGRESS=1

COPY pyproject.toml ./
RUN uv sync --frozen --no-cache --no-dev --no-install-project

# --- Stage 2: runtime ---
FROM python:3.12-slim-bookworm

WORKDIR /app

ENV PYTHONUNBUFFERED=1 \
    PATH="/app/.venv/bin:$PATH"

RUN useradd -m -u 1000 bedrock_agentcore

COPY --from=builder /app/.venv /app/.venv
COPY --chown=bedrock_agentcore:bedrock_agentcore . .

USER bedrock_agentcore

EXPOSE 8080

CMD ["python", "main.py"]
```

This Dockerfile uses a two-stage build inspired by the template the [AgentCore CLI generates](https://github.com/aws/agentcore-cli/blob/main/src/assets/container/python/Dockerfile), with these design choices:

- **Multi-stage** — `uv` is only in the builder stage; the final image uses a plain Python base (smaller)
- **Layer caching** — dependencies are installed before copying application code
- **Non-root** — runs as `bedrock_agentcore` (UID 1000)

### 3. Build and push to ECR

```bash
ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)
REGION=us-west-2
REPO_NAME=my_agent

# Build for ARM64
docker buildx build --platform linux/arm64 -t my_agent:latest my_agent/

# Create ECR repository (one-time)
aws ecr create-repository --repository-name $REPO_NAME --region $REGION

# Authenticate Docker to ECR
aws ecr get-login-password --region $REGION | \
  docker login --username AWS --password-stdin $ACCOUNT_ID.dkr.ecr.$REGION.amazonaws.com

# Tag and push
docker tag my_agent:latest $ACCOUNT_ID.dkr.ecr.$REGION.amazonaws.com/$REPO_NAME:latest
docker push $ACCOUNT_ID.dkr.ecr.$REGION.amazonaws.com/$REPO_NAME:latest
```

### 4. Create the Agent Runtime

```bash
aws bedrock-agentcore create-agent-runtime \
  --agent-runtime-name my_agent \
  --agent-runtime-artifact \
    "containerConfiguration={containerUri=$ACCOUNT_ID.dkr.ecr.$REGION.amazonaws.com/$REPO_NAME:latest}" \
  --region $REGION
```

### 5. Test the deployed agent

```bash
sca client remote \
  --arn arn:aws:bedrock-agentcore:$REGION:$ACCOUNT_ID:runtime/my_agent \
  --region $REGION
```

---

## Multiple Agents

You can deploy multiple agents in the same AgentCore project (Paths A and B). Each agent gets its own runtime ARN and its own set of microVMs:

```bash
# Create agent directories
mkdir agent_one agent_two

# Add main.py, config.yaml, pyproject.toml to each (see Required Files above)

# Register first agent
agentcore add agent
  --type byo \
  --name agent_one \
  --code-location agent_one \
  --entrypoint main.py \
  --language Python \
  --framework Strands \
  --model-provider Bedrock

# Register second agent
agentcore add agent
  --type byo \
  --name agent_two \
  --code-location agent_two \
  --entrypoint main.py \
  --language Python \
  --framework Strands \
  --model-provider Bedrock

# Deploy all at once
agentcore deploy -y
```

## How the Runtime Discovers Your App

At runtime, the deployed environment imports your entrypoint module and looks for a module-level `app` variable — a Starlette/ASGI application. By default, `main.py` becomes `main:app`.

## IAM Permissions

Your AWS credentials need permissions for:

- **[Bedrock](https://docs.aws.amazon.com/bedrock/latest/userguide/)** — `bedrock:InvokeModel` for the models in your config
- **[AgentCore](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/)** — permissions to create/manage agent runtimes
- **[S3](https://docs.aws.amazon.com/s3/)** — if using S3 session manager
- **[CloudWatch Logs](https://docs.aws.amazon.com/AmazonCloudWatch/latest/logs/)** — for runtime logs

> For detailed IAM policies, see the [AgentCore IAM documentation](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/security-iam.html).

## Next

[Chapter 07 — The Client](Chapter_07.md)
