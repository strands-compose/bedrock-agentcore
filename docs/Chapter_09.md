# Chapter 09 — Deployment Strategies

This chapter explains how strands-compose-agentcore fits into different deployment workflows — from a solo developer shipping a quick prototype to an enterprise platform team managing dozens of agents across environments.

The key point: **`create_app()` is the only thing you need from this package to deploy.** Everything else — how you package, ship, and manage infrastructure — depends on your team and tooling.

---

## The Core: `create_app()`

Regardless of how you deploy, your entry script looks the same:

```python
# main.py
from pathlib import Path
from strands_compose_agentcore import create_app

app = create_app(Path(__file__).parent / "config.yaml")
```

This factory handles the AgentCore runtime contract — ASGI lifecycle, session management, event streaming, concurrency guards, health checks. You don't need to know how `BedrockAgentCoreApp` works, what headers AgentCore sends, or how SSE streaming is wired. The factory does it all.

Your deployment strategy only affects how this `main.py` + `config.yaml` + dependencies reach the runtime.

---

## Path 1: Individual Developers — AgentCore CLI

**Best for:** Solo developers, small teams, prototyping, hackathons, quick experiments.

The [AgentCore CLI](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/agentcore-cli.html) (`npm install -g @aws/agentcore`) is a Node.js tool that manages the full lifecycle: project scaffolding, agent registration, packaging (CodeZip or Container), deployment via CloudFormation, logs, and status.

We recommend it for individual projects because it handles everything with minimal setup:

```bash
# Scaffold a project
agentcore create --name project --no-agent
cd project

# Add your agent files (main.py, config.yaml, pyproject.toml)
mkdir my_agent && cp ../my_agent/* my_agent/

# Register
agentcore add agent --type byo --name my_agent --code-location my_agent \
  --entrypoint main.py --language Python --framework Strands --model-provider Bedrock

# Test locally (with streaming event rendering)
sca dev --config my_agent/config.yaml

# Deploy
agentcore deploy

# Test the deployed agent
sca client remote --arn <ARN> --region us-west-2
```

This is the workflow described in [Chapter 06](Chapter_06.md) (Paths A and B). The AgentCore CLI manages CloudFormation stacks, S3 artifacts, ECR repositories, and IAM roles for you.

### What the AgentCore CLI provides

- `agentcore create` — project scaffolding
- `agentcore add agent` — agent registration and config generation
- `agentcore deploy` — packaging + CloudFormation deployment
- `agentcore status` — runtime status and ARN lookup
- `agentcore logs` — CloudWatch log streaming
- `agentcore dev` — local dev server (plain text output)
- `agentcore invoke` — send a prompt to a deployed agent (plain text output)

### What we add

- `sca dev` — local dev server with strands-compose `AnsiRenderer` for streaming event display (tokens, tool calls, handoffs, completions rendered with color and typewriter effects)
- `sca client local` / `sca client remote` — interactive REPL with the same streaming renderer
- `AgentCoreClient` — async Python client for programmatic access

We don't wrap, replace, or duplicate the AgentCore CLI. We recommend it. Our CLI commands exist solely because `agentcore dev` and `agentcore invoke` treat SSE responses as plain text — they can't parse or render the structured `StreamEvent` objects that strands-compose agents produce.

---

## Path 2: Enterprise Teams — IaC + CI/CD

**Best for:** Platform teams, multi-environment deployments, regulated industries, teams with existing IaC and CI/CD pipelines.

Enterprise teams typically don't use interactive CLIs for production deployments. They have Terraform, CDK, CloudFormation, or Pulumi managing infrastructure, and CI/CD pipelines (GitHub Actions, GitLab CI, CodePipeline, Jenkins) handling builds and deploys.

For these teams, `create_app()` is the only thing you need from this package. The AgentCore CLI is entirely optional — it's a convenient tool for development, not a deployment dependency.

### Docker Image → ECR → Agent Runtime

The most common enterprise pattern: build a Docker image in CI, push to ECR, and update the agent runtime to use the new image.

**Your repo structure:**

```
my-agent-system/
├── config.yaml
├── main.py
├── pyproject.toml
├── Dockerfile
└── terraform/
    └── main.tf          # or CDK, CloudFormation, Pulumi
```

**Dockerfile** (same as [Chapter 06 — Path C](Chapter_06.md#path-c--manual-container-deployment)):

```dockerfile
FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim AS builder
WORKDIR /app
ENV UV_COMPILE_BYTECODE=1 UV_NO_PROGRESS=1
COPY pyproject.toml ./
RUN uv sync --frozen --no-cache --no-dev --no-install-project

FROM python:3.12-slim-bookworm
WORKDIR /app
ENV PYTHONUNBUFFERED=1 PATH="/app/.venv/bin:$PATH"
RUN useradd -m -u 1000 bedrock_agentcore
COPY --from=builder /app/.venv /app/.venv
COPY --chown=bedrock_agentcore:bedrock_agentcore . .
USER bedrock_agentcore
EXPOSE 8080
CMD ["python", "main.py"]
```

**CI pipeline (GitHub Actions example):**

```yaml
name: Deploy Agent
on:
  push:
    branches: [main]

jobs:
  deploy:
    runs-on: ubuntu-latest
    permissions:
      id-token: write
      contents: read
    steps:
      - uses: actions/checkout@v4

      - uses: aws-actions/configure-aws-credentials@v4
        with:
          role-to-assume: arn:aws:iam::role/deploy-role
          aws-region: us-west-2

      - uses: aws-actions/amazon-ecr-login@v2

      - name: Build and push
        run: |
          docker buildx build --platform linux/arm64 \
            -t ${{ env.ECR_REGISTRY }}/my-agent:${{ github.sha }} \
            -t ${{ env.ECR_REGISTRY }}/my-agent:latest \
            --push .

      - name: Update agent runtime
        run: |
          aws bedrock-agentcore update-agent-runtime \
            --agent-runtime-id $RUNTIME_ID \
            --agent-runtime-artifact \
              "containerConfiguration={containerUri=$ECR_REGISTRY/my-agent:${{ github.sha }}}"
```

**Terraform (infrastructure):**

```hcl
resource "aws_bedrockagentcore_agent_runtime" "my_agent" {
  agent_runtime_name = "my-agent"

  agent_runtime_artifact {
    container_configuration {
      container_uri = "${aws_ecr_repository.my_agent.repository_url}:latest"
    }
  }
}

resource "aws_ecr_repository" "my_agent" {
  name = "my-agent"
}
```

The CI pipeline builds and pushes the image; Terraform (or CDK, CloudFormation) manages the runtime resource. No AgentCore CLI involved.

### CodeZip → S3 → Agent Runtime

If your team prefers CodeZip over containers (simpler, no Docker, 250 MB limit):

**CI pipeline:**

```yaml
- name: Package and upload
  run: |
    # Install deps into staging directory
    pip install --target staging/ -r pyproject.toml
    cp main.py config.yaml staging/

    # Zip and upload to S3
    cd staging && zip -r ../agent.zip .
    aws s3 cp ../agent.zip s3://my-deploy-bucket/my-agent/agent.zip

- name: Update agent runtime
  run: |
    aws bedrock-agentcore update-agent-runtime \
      --agent-runtime-id $RUNTIME_ID \
      --agent-runtime-artifact \
        "s3Configuration={s3Uri=s3://my-deploy-bucket/my-agent/agent.zip}"
```

Same pattern: CI packages and uploads; IaC manages the runtime resource.

### Multi-Environment Deployments

Enterprise teams typically deploy the same agent across dev, staging, and production:

```
environments/
├── dev/
│   ├── config.yaml        # dev model, debug logging
│   └── terraform.tfvars
├── staging/
│   ├── config.yaml        # staging model
│   └── terraform.tfvars
└── prod/
    ├── config.yaml        # production model, minimal logging
    └── terraform.tfvars
```

The `main.py` is identical everywhere — only `config.yaml` and infrastructure settings change. `create_app()` reads whatever config file you point it at.

---

## Relationship with the AgentCore CLI

To be explicit about what we do and don't do:

| | AgentCore CLI | strands-compose-agentcore |
|---|---|---|
| **Project scaffolding** | ✅ `agentcore create` | ❌ Not our job |
| **Agent registration** | ✅ `agentcore add agent` | ❌ Not our job |
| **Packaging (zip/container)** | ✅ `agentcore deploy` | ❌ Not our job |
| **CloudFormation deployment** | ✅ `agentcore deploy` | ❌ Not our job |
| **Log streaming** | ✅ `agentcore logs` | ❌ Not our job |
| **Runtime status** | ✅ `agentcore status` | ❌ Not our job |
| **ASGI app factory** | ❌ | ✅ `create_app()` |
| **Streaming event rendering** | ❌ Plain text only | ✅ `sca dev`, `sca client` |
| **Programmatic client** | ❌ | ✅ `AgentCoreClient` |

We don't wrap, replace, or compete with the AgentCore CLI. We recommend it for development workflows. But it is not a prerequisite — you can deploy strands-compose-agentcore apps with any tool that can create an AgentCore agent runtime resource (AWS CLI, Terraform, CDK, CloudFormation, Pulumi, or even the AWS Console).

---

## Which Path Should You Choose?

| Scenario | Recommendation |
|----------|---------------|
| Solo developer, quick prototype | AgentCore CLI (Path A — CodeZip) |
| Small team, simple agents | AgentCore CLI (Path A or B) |
| Need custom system deps or large artifacts | AgentCore CLI with Container build (Path B) |
| Existing IaC (Terraform, CDK) | Docker → ECR → IaC-managed runtime |
| CI/CD pipeline already in place | Docker or CodeZip → S3 → pipeline-managed runtime |
| Multi-environment (dev/staging/prod) | IaC + CI/CD, different `config.yaml` per environment |
| Regulated industry, audit requirements | IaC with state tracking + CI/CD with approval gates |

The `main.py` with `create_app()` is identical in every scenario. Only the packaging and deployment mechanism changes.

## Previous

[Chapter 08 — Advanced Topics](Chapter_08.md)
