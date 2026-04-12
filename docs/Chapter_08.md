# Chapter 08 — Advanced Topics

This chapter covers operational concerns, production configuration, and deployment variations that go beyond the basics in earlier chapters.

## VPC Configuration

If your agent needs to access resources in a VPC (databases, internal APIs, private MCP servers), configure networking when you register the agent:

```bash
agentcore add agent \
  --type byo \
  --name my_agent \
  --code-location my_agent \
  --network-mode VPC \
  --vpc-id vpc-12345 \
  --subnet-ids subnet-aaa,subnet-bbb \
  --security-group-ids sg-12345 \
  --language Python \
  --framework Strands \
  --model-provider Bedrock
```

These flags are passed to `agentcore add agent`. The agent runtime will be placed in the specified VPC with the given subnets and security groups.

> For VPC configuration details, see the [AgentCore networking docs](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/agentcore-vpc.html).

---

## Logging in Production

In production on AgentCore Runtime, `BedrockAgentCoreApp` installs a JSON `StreamHandler` on the `bedrock_agentcore.app` logger. stdout/stderr are captured by AgentCore and forwarded to [CloudWatch](https://docs.aws.amazon.com/AmazonCloudWatch/latest/logs/), where JSON-formatted log lines appear as structured, filterable entries.

View logs with:

```bash
agentcore logs --name my_agent
```

Or navigate to [CloudWatch Logs](https://console.aws.amazon.com/cloudwatch/home#logsV2:log-groups) in the AWS console.

### Log Levels

| Logger | Controlled By | Default |
|--------|--------------|---------|
| `bedrock_agentcore.app` | `BedrockAgentCoreApp` (always INFO) | INFO |
| `strands_compose` | `log_level` in YAML config | WARNING |
| `strands_compose_agentcore` | Python `logging` config | WARNING |
| Your own loggers | Python `logging` config | WARNING |

To see strands-compose internal logs in CloudWatch, set `log_level: INFO` in your YAML config. To see your own application logs, configure Python's logging module in your entry script:

```python
import logging
logging.basicConfig(level=logging.INFO)
```

During local development, the `dev` command suppresses the JSON handler automatically via `suppress_runtime_logging=True` (see [Chapter 03](Chapter_03.md)).

---

## Timeouts

AgentCore Runtime has built-in timeouts, and your strands-compose orchestrations have their own configurable timeouts. These operate independently:

| Timeout | Where | Default |
|---------|-------|---------|
| Session idle timeout | AgentCore Runtime | 900s (15 min) |
| Swarm execution timeout | YAML `execution_timeout` | 900s (15 min) |
| Swarm per-node timeout | YAML `node_timeout` | 300s (5 min) |
| Graph execution timeout | YAML `execution_timeout` | Service-defined |
| Graph per-node timeout | YAML `node_timeout` | Service-defined |
| HTTP read timeout | `AgentCoreClient(timeout=...)` | botocore default |

The session idle timeout is controlled by `--idle-timeout` when registering the agent with `agentcore add agent` (range: 60–28800 seconds). After this period of inactivity, the microVM is shut down. For long-running async tasks, `BedrockAgentCoreApp` reports `HEALTHY_BUSY` on `/ping` while work is in progress via `add_async_task()`, which prevents the runtime from considering the session idle.

---

## Multi-File Configs

Split large configs across multiple YAML files:

```python
app = create_app(["base.yaml", "agents.yaml", "tools.yaml"])
```

Collection sections (`models`, `agents`, `mcp_servers`, `mcp_clients`, `orchestrations`) are merged across files. Singleton fields (`entry`, `session_manager`, `log_level`) use last-wins semantics — the value from the last file in the list takes precedence. This is useful for sharing common model definitions across environments while keeping agent-specific configs separate.

---

## MCP Server Connectivity

At startup, the ASGI lifespan enters the strands-compose MCP lifecycle: stdio-based MCP servers are launched, SSE-based MCP clients connect to their targets, and a validation report is printed summarizing available tools per server. If an MCP connection fails at startup, the validation report shows the failure but the app still starts — broken connections will cause runtime errors only when the agent actually tries to use those tools.

---

## Health Checks

The app exposes a `GET /ping` endpoint managed by `BedrockAgentCoreApp`:

| Response | Meaning |
|----------|---------|
| `HEALTHY` | Server is idle, ready for invocations |
| `HEALTHY_BUSY` | An invocation is in progress |

AgentCore Runtime uses this endpoint to manage traffic routing and scaling. When an invocation is in progress, the concurrency guard in the `/invocations` entrypoint registers an async task via `app.add_async_task("invoke")`, which causes `/ping` to return `HEALTHY_BUSY`. This prevents AgentCore from routing additional requests to a busy microVM.

---

## CDK Deployment

For infrastructure-as-code workflows, you can deploy AgentCore agents using [AWS CDK](https://docs.aws.amazon.com/cdk/v2/guide/home.html) instead of the AgentCore CLI. CDK deployment is managed entirely by CDK and CloudFormation — strands-compose-agentcore is not involved in the deployment process itself.

## Next

[Chapter 09 — Deployment Strategies](Chapter_09.md)
