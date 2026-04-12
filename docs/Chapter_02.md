# Chapter 02 — Getting Started

## Install

```bash
pip install strands-compose-agentcore
```

This single install pulls in the full dependency chain: [strands-compose](https://github.com/strands-compose/sdk-python) for YAML config parsing and agent resolution, [bedrock-agentcore](https://pypi.org/project/bedrock-agentcore/) for the ASGI runtime, and [boto3](https://pypi.org/project/boto3/) for AWS API calls. You do not need to install any of these separately.

If you plan to deploy to AWS (rather than just running locally), you also need the [AgentCore CLI](https://github.com/aws/agentcore-cli) — a Node.js tool that handles packaging, CloudFormation, and deployment:

```bash
npm install -g @aws/agentcore
```

> See the [AgentCore CLI installation docs](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/agentcore-cli.html) for prerequisites.

## AWS Credentials

You need valid AWS credentials with access to [Amazon Bedrock](https://docs.aws.amazon.com/bedrock/latest/userguide/) models. The simplest setup:

```bash
aws configure
```

Or set environment variables:

```bash
export AWS_ACCESS_KEY_ID=...
export AWS_SECRET_ACCESS_KEY=...
export AWS_DEFAULT_REGION=us-west-2
```

Make sure the Bedrock model you reference in `config.yaml` is enabled in your account. Check the [Bedrock model access page](https://console.aws.amazon.com/bedrock/home#/modelaccess) in the AWS console. For available model IDs, see [Supported models](https://docs.aws.amazon.com/bedrock/latest/userguide/models-supported.html).

## Write a Config

Create a `config.yaml`:

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

This defines one model and one agent. The `entry` field specifies which agent handles incoming requests. All YAML config options are defined by strands-compose — see the [strands-compose documentation](https://github.com/strands-compose/sdk-python) for the full reference.

## Run Locally

### Option A — Dev CLI (recommended)

The fastest way to see your agent working is the `dev` command, which starts an HTTP server and an interactive REPL in a single terminal:

```bash
sca dev --config config.yaml
```

Type a message and press Enter. You will see the agent's response streamed back with colored output. The server runs in a background daemon thread while the REPL runs in the foreground, so both share the same process — exiting the REPL stops everything.

### Option B — Entry script + separate client

For more control, create a `main.py` entry script and connect to it with a separate REPL client. This is the same pattern used when deploying to AgentCore Runtime, so it is a good way to verify your agent works exactly as it will in production.

```python
# main.py
from pathlib import Path
from strands_compose_agentcore import create_app

app = create_app(Path(__file__).parent / "config.yaml")

if __name__ == "__main__":
    app.run(port=8080)
```

Run it:

```bash
python main.py
```

Then connect with the REPL in a second terminal:

```bash
sca client local
```

You also need a `pyproject.toml` to declare the dependency for deployment:

```toml
[project]
name = "my-agent"
requires-python = ">=3.11"
dependencies = [
    "strands-compose-agentcore",
]
```

These three files — `main.py`, `config.yaml`, and `pyproject.toml` — are all you need for both local development and deployment. See [Chapter 06](Chapter_06.md) for the full deployment guide.

## What's Next

| Want to... | Read |
|------------|------|
| Understand how the app factory works | [Chapter 03 — The App Factory](Chapter_03.md) |
| Learn about sessions and streaming | [Chapter 04 — Session & Streaming](Chapter_04.md) |
| Explore all CLI commands | [Chapter 05 — The CLI](Chapter_05.md) |
| Deploy to production | [Chapter 06 — Deployment](Chapter_06.md) |
| Invoke agents from your own code | [Chapter 07 — The Client](Chapter_07.md) |

## Next

[Chapter 03 — The App Factory](Chapter_03.md)
