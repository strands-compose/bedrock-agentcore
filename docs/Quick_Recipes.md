# Quick Recipes — AWS Tooling Reference

A quick reference for the AWS services and tools involved in the strands-compose-agentcore workflow. For the `sca` CLI commands, see [Chapter 05](Chapter_05.md). For the AgentCore CLI commands, see the [AgentCore CLI commands reference](https://github.com/aws/agentcore-cli/blob/main/docs/commands.md).

## AWS Services

### Amazon Bedrock AgentCore Runtime

Managed compute for running AI agents. Provides session-isolated microVMs, session routing via the `X-Amzn-Bedrock-AgentCore-Runtime-Session-Id` header, health checks via `/ping`, and auto-scaling. Hosts your `BedrockAgentCoreApp` and routes `/invocations` requests to your agent.

**Docs:** [AgentCore Runtime documentation](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/agents-tools-runtime.html)

---

### Amazon Bedrock

Fully managed service for foundation models. Provides inference for Claude, Llama, Mistral, and other models. Referenced by `provider: bedrock` in your YAML config.

**Docs:** [Bedrock User Guide](https://docs.aws.amazon.com/bedrock/latest/userguide/) · [Supported models](https://docs.aws.amazon.com/bedrock/latest/userguide/models-supported.html) · [Model access](https://console.aws.amazon.com/bedrock/home#/modelaccess)

---

### Amazon Bedrock AgentCore Memory

Managed memory service for AI agents. Used by the `agentcore` session manager provider to persist conversation history as immutable events with support for short-term and long-term memory retrieval. See [Chapter 04](Chapter_04.md) for configuration details.

**Docs:** [AgentCore Memory documentation](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/memory.html)

---

### Amazon CloudWatch Logs

Log management service that collects, stores, and makes logs searchable. Receives structured JSON logs from your deployed agent. View with `agentcore logs` or the CloudWatch console.

**Docs:** [CloudWatch Logs documentation](https://docs.aws.amazon.com/AmazonCloudWatch/latest/logs/)

---

### Amazon S3

Object storage. Optional session persistence backend — use `provider: s3` in `session_manager` config for cross-deployment conversation persistence without AgentCore Memory features.

**Docs:** [S3 documentation](https://docs.aws.amazon.com/s3/)

---

### Amazon ECR

Container registry. Stores Docker images for container-based deployments (Path B in [Chapter 06](Chapter_06.md)). Only needed if you choose container deployment instead of CodeZip.

**Docs:** [ECR documentation](https://docs.aws.amazon.com/ecr/)

---

### AWS IAM

Identity and access management. Controls permissions for deploying agents, invoking models, and accessing resources.

Key permissions:
- `bedrock:InvokeModel` — call Bedrock models
- `bedrock-agentcore:InvokeAgentRuntime` — invoke deployed agents
- `s3:GetObject` / `s3:PutObject` — S3 session persistence

**Docs:** [IAM documentation](https://docs.aws.amazon.com/IAM/latest/UserGuide/)

---

## Tools

### AgentCore CLI (`@aws/agentcore`)

Node.js CLI for creating and managing AgentCore projects and deployments. Handles packaging, CDK synthesis, and CloudFormation deployment.

**Install:** `npm install -g @aws/agentcore`

**Docs:** [AgentCore CLI documentation](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/runtime-get-started-cli.html) · [Commands reference](https://github.com/aws/agentcore-cli/blob/main/docs/commands.md) · [GitHub](https://github.com/aws/agentcore-cli)

---

### AWS CLI

General-purpose CLI for all AWS services. Used for credential setup (`aws configure`), ECR authentication, and direct API access.

**Install:** [AWS CLI installation guide](https://docs.aws.amazon.com/cli/latest/userguide/getting-started-install.html)

---

## Python Packages

| Package | Purpose | Install |
|---------|---------|---------|
| `strands-compose-agentcore` | This package — CLI + app factory + clients | `pip install strands-compose-agentcore` |
| `strands-compose` | YAML config parsing, agent resolution, streaming | Transitive dependency |
| `strands-agents` | Agent framework (Agent, tools, hooks) | Transitive dependency |
| `bedrock-agentcore` | `BedrockAgentCoreApp` ASGI server + AgentCore Memory integration | Transitive dependency |
| `boto3` | AWS SDK for Python | Transitive dependency |

You only need to install `strands-compose-agentcore` — everything else comes as a transitive dependency.

---

## Links

- [strands-compose GitHub](https://github.com/strands-compose/sdk-python)
- [strands-agents GitHub](https://github.com/strands-agents/sdk-python)
- [AgentCore CLI GitHub](https://github.com/aws/agentcore-cli/tree/main)
- [AgentCore Runtime docs](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/)
- [Bedrock model IDs](https://docs.aws.amazon.com/bedrock/latest/userguide/models-supported.html)
