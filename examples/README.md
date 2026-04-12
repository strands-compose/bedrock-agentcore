# strands-compose-agentcore Examples

Two examples that walk you from local prototyping to production deployment.

| # | Folder | Stage | What it demonstrates |
|---|--------|-------|----------------------|
| 01 | [01_quick_start](./01_quick_start/README.md) | Develop | Multi-agent delegate orchestration + `dev` CLI — talk to your agents in one command |
| 02 | [02_deploy](./02_deploy/README.md) | Deploy | End-to-end guide: create files → test → deploy → connect |

## Prerequisites

- AWS credentials configured (`aws configure` or environment variables)
- Bedrock model access enabled in the [Bedrock console](https://console.aws.amazon.com/bedrock/)
- Dependencies installed: `pip install strands-compose-agentcore`

Update `model_id` in each `config.yaml` to match your Bedrock model availability.

**For deployment (example 02):** The [`agentcore` CLI](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/agentcore-cli.html) is a Node.js tool provided by AWS — install it with `npm install -g @aws/agentcore` (requires Node.js 20+).

## Quick start

```bash
sca dev --config examples/01_quick_start/config.yaml
```

For advanced topics (VPC, containers, CDK, observability, logging), see the [docs](../docs/README.md).
