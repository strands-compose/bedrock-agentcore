# Chapter 08 — Advanced Topics

This chapter covers operational concerns, production configuration, and deployment variations that go beyond the basics in earlier chapters.

## VPC Configuration

If your agent needs to reach resources in a VPC (databases, internal APIs, privately hosted MCP servers), configure networking when you register the agent:

```bash
agentcore add agent \
  --type byo \
  --name my_agent \
  --code-location my_agent \
  --network-mode VPC \
  --subnets subnet-aaa,subnet-bbb \
  --security-groups sg-12345 \
  --language Python \
  --framework Strands \
  --model-provider Bedrock
```

These flags are passed to `agentcore add agent`. The agent runtime will be placed in the given subnets and security groups. Container builds (`--build Container`) also need `--vpc-id`. In VPC mode the agent may need VPC endpoints (or a NAT gateway) for CloudWatch, X-Ray, ECR, and Bedrock.

> For VPC configuration details, see the [AgentCore networking docs](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/agentcore-vpc.html).

---

## Logging in Production

In production on AgentCore Runtime, `BedrockAgentCoreApp` installs a JSON `StreamHandler` (stderr) on the `bedrock_agentcore.app` logger. AgentCore writes stdout/stderr to the `[runtime-logs]` streams of the agent's [CloudWatch](https://docs.aws.amazon.com/AmazonCloudWatch/latest/logs/) log group, but those streams may be incomplete for invocation logs. For reliable application logs and traces, run the agent under ADOT — see [Chapter 10 — Observability](Chapter_10.md).

View logs with:

```bash
agentcore logs --runtime my_agent
```

Or navigate to [CloudWatch Logs](https://console.aws.amazon.com/cloudwatch/home#logsV2:log-groups) in the AWS console.

### Log Levels

| Logger | Controlled By | Default |
|--------|--------------|---------|
| `bedrock_agentcore.app` | `BedrockAgentCoreApp` (own JSON handler) | INFO |
| `strands_compose` | `log_level` in YAML config | WARNING |
| `strands_compose_agentcore` | Python `logging` config | Root level |
| Your own loggers | Python `logging` config | Root level |

The root level is WARNING under plain `python main.py` and INFO under ADOT's `opentelemetry-instrument`. `create_app` applies the YAML `log_level` to the `strands_compose` logger when it parses the config from a path or YAML string; with a pre-built `AppConfig` it leaves the level alone. Set other loggers in your entry script, e.g. `logging.getLogger("strands_compose_agentcore").setLevel(logging.INFO)`. Without ADOT, `logging.basicConfig(level=logging.INFO)` shows INFO logs; under ADOT it is a no-op ([Chapter 10](Chapter_10.md)).

During local development, the `dev` command suppresses the JSON handler automatically via `suppress_runtime_logging=True` (see [Chapter 03](Chapter_03.md)).

---

## Timeouts

AgentCore Runtime has built-in timeouts, and your strands-compose orchestrations have their own configurable timeouts. These operate independently:

| Timeout | Where | Default |
|---------|-------|---------|
| Session idle timeout | AgentCore Runtime | 900s (15 min) |
| Swarm execution timeout | YAML `execution_timeout` | 900s (15 min) |
| Swarm per-node timeout | YAML `node_timeout` | 300s (5 min) |
| Graph execution timeout | YAML `execution_timeout` | None (no limit) |
| Graph per-node timeout | YAML `node_timeout` | None (no limit) |
| Agent invocation timeout | `create_app(invocation_timeout=...)` | None (no limit) |
| HTTP read timeout | `AgentCoreClient(timeout=...)` | botocore default |

The session idle timeout is controlled by `--idle-timeout` when registering the agent with `agentcore add agent` (range: 60–28800 seconds). After this period of inactivity, the microVM is shut down. For long-running async tasks, `BedrockAgentCoreApp` reports `HealthyBusy` on `/ping` while work is in progress via `add_async_task()`, which prevents the runtime from considering the session idle.

---

## Idle Connections on AWS

`AgentCoreClient` reuses its HTTPS connections. On AWS, NAT gateways, VPC endpoints and Network Load Balancers forget a TCP connection after **350 s** without traffic ([AWS blog](https://aws.amazon.com/blogs/networking-and-content-delivery/implementing-long-running-tcp-connections-within-vpc-networking/)). When that happens, the next call sends its request on a connection nobody answers. It waits for the read timeout (60 s by default), then botocore retries on a new connection.

The client turns on TCP keepalive, but the operating system decides when to send the first probe. On Linux that is `net.ipv4.tcp_keepalive_time`, 7200 s by default, far beyond 350 s. botocore has no setting for it ([boto/botocore#2916](https://github.com/boto/botocore/issues/2916)), so set it on the host running the client to a value below 350, for example `60`:

| Where the client runs | How to set it |
|---|---|
| ECS (on Fargate, platform version 1.4.0 or later) | Task definition, in the container definition: `"systemControls": [{ "namespace": "net.ipv4.tcp_keepalive_time", "value": "60" }]` |
| Docker / Docker Compose | `docker run --sysctl net.ipv4.tcp_keepalive_time=60`, or `sysctls:` in the Compose service |
| EC2 or another Linux host | `sysctl -w net.ipv4.tcp_keepalive_time=60`, persisted in `/etc/sysctl.d/` |

Only sockets with keepalive turned on are affected, so the change is safe for the rest of the container. To check it inside a running task, `cat /proc/sys/net/ipv4/tcp_keepalive_time` should print `60`.

---

## Multi-File Configs

Split large configs across multiple YAML files:

```python
app = create_app(["base.yaml", "agents.yaml", "tools.yaml"])
```

Collection sections (`models`, `agents`, `mcp_clients`, `orchestrations`) are merged across files; a name defined in two files raises an error. Singleton fields (`entry`, `session_manager`, `log_level`) use last-wins semantics — the value from the last file in the list takes precedence. This is useful for sharing common model definitions across environments while keeping agent-specific configs separate.

---

## MCP Connectivity

MCP clients are built with the rest of the session, on the first invocation. strands starts each client when the agent that uses it is constructed, so an unreachable server fails that first invocation with an error event rather than failing at startup.

Shutdown is handled for you. strands stops an MCP client — including a `command:` subprocess — from `Agent.__del__`, which fires as soon as the last reference to the agent goes away, and on process exit the subprocess dies with its parent regardless.

The one gap is session replacement. A delegate orchestration wires the delegated agent in as a tool, which puts it in a reference cycle that refcounting cannot reap, so its subprocess would keep running inside a still-live process until an arbitrary later garbage-collection pass. The adapter therefore calls `Agent.cleanup()` explicitly before swapping a cached session out.

---

## Health Checks

The app exposes a `GET /ping` endpoint managed by `BedrockAgentCoreApp`:

| Response | Meaning |
|----------|---------|
| `Healthy` | Server is idle, ready for invocations |
| `HealthyBusy` | An invocation is in progress |

AgentCore Runtime uses this endpoint for health monitoring and session lifecycle: while `/ping` reports `HealthyBusy`, the session is considered active and is kept alive past the idle timeout. The `/invocations` entrypoint registers each invocation via `app.add_async_task("invoke")`, so `/ping` returns `HealthyBusy` until it finishes. A second invocation that arrives meanwhile is rejected with an `AgentBusy` error event.

---

## CDK Deployment

For infrastructure-as-code workflows, you can deploy AgentCore agents using [AWS CDK](https://docs.aws.amazon.com/cdk/v2/guide/home.html) instead of the AgentCore CLI. CDK deployment is managed entirely by CDK and CloudFormation — strands-compose-agentcore is not involved in the deployment process itself.

## Next

[Chapter 09 — Deployment Strategies](Chapter_09.md)
