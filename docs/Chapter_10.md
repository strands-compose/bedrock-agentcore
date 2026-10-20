# Chapter 10 — Observability

Optional, but recommended for anything beyond a prototype: send your agent's logs, traces, and token usage to [Amazon CloudWatch](https://docs.aws.amazon.com/AmazonCloudWatch/latest/monitoring/) with OpenTelemetry.

[OpenTelemetry](https://opentelemetry.io/docs/what-is-opentelemetry/) (OTEL) is the open standard for application telemetry — logs, traces (a tree of timed *spans* per request), and metrics. AWS ships its own build, the [AWS Distro for OpenTelemetry (ADOT)](https://aws-otel.github.io/docs/introduction), and AgentCore Runtime is pre-wired for it: every runtime container receives the environment variables that point ADOT at the agent's CloudWatch log group. Strands Agents already emits OTEL spans for every agent call, model call, and tool call — ADOT just has to be present to ship them.

> **Reference:** [AgentCore observability](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/observability.html) · [Add observability to AgentCore](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/observability-configure.html) · [View observability data](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/observability-view.html)

---

## How It Works

```
┌──────────── AgentCore Runtime microVM ────────────┐
│  opentelemetry-instrument python main.py          │
│    ├─ Python logging  ──┐                         │
│    └─ Strands spans   ──┤  ADOT (OTLP over HTTPS) │
└─────────────────────────┼─────────────────────────┘
                          ▼
   CloudWatch log group /aws/bedrock-agentcore/runtimes/<agent_id>-<endpoint>
     ├─ otel-rt-logs   ← your log records
     └─ spans          ← traces (requires Transaction Search)
```

There is no collector or sidecar to run. ADOT sends telemetry straight to the CloudWatch endpoints using the runtime's execution role.

## What You Get

| Data | Where | Contains |
|------|-------|----------|
| Application logs | `otel-rt-logs` stream | Python log records at INFO and above (`bedrock_agentcore.app`, `strands_compose_agentcore`, your own loggers; `strands_compose` follows the YAML `log_level`, default WARNING), tagged with trace and span IDs |
| Traces | `spans` stream | `POST /invocations` → `invoke_agent` → `execute_event_loop_cycle` → `chat` / tool spans, with model ID, token usage, and latency |
| Dashboard | [CloudWatch GenAI Observability](https://console.aws.amazon.com/cloudwatch/home#gen-ai-observability/agent-core) → Bedrock AgentCore | Sessions, traces, token usage per model, errors, latency |

---

## Enable It

### 1. Add ADOT to your dependencies

```toml
[project]
name = "my-agent"
version = "0.1.0"
requires-python = ">=3.11"
dependencies = [
    "strands-compose-agentcore",
    "aws-opentelemetry-distro>=0.18.0",
]
```

This is required on **every** deployment path. `strands-compose-agentcore` does not depend on ADOT, so without this line nothing is exported — even when the entrypoint is wrapped with `opentelemetry-instrument`.

### 2. Start the agent with `opentelemetry-instrument`

| Path ([Chapter 06](Chapter_06.md)) | What to do |
|------|------------|
| A — CLI + CodeZip | Nothing. The AgentCore CLI wraps the entrypoint with `opentelemetry-instrument` by default |
| B — CLI + Container | Use the `CMD` below in your Dockerfile — the CLI doesn't generate one for `--type byo` agents |
| C — Manual container | Use the `CMD` below in your Dockerfile |

```dockerfile
CMD ["opentelemetry-instrument", "python", "main.py"]
```

[examples/02_deploy](../examples/02_deploy/) has a complete [Dockerfile](../examples/02_deploy/Dockerfile) and [pyproject.toml](../examples/02_deploy/pyproject.toml) with both changes.

You don't set any `OTEL_*` variables yourself — AgentCore Runtime injects them (`AGENT_OBSERVABILITY_ENABLED`, `OTEL_PYTHON_DISTRO`, `OTEL_EXPORTER_OTLP_LOGS_HEADERS`, …), and ADOT turns on log and trace export when it sees them.

### 3. Turn on Transaction Search (traces only, once per account and region)

Logs work without this step. Traces and the dashboard need [CloudWatch Transaction Search](https://docs.aws.amazon.com/AmazonCloudWatch/latest/monitoring/Enable-TransactionSearch.html), which is **off** in a new account. Indexing 1% of spans is free; a higher percentage is billed per indexed span ([CloudWatch pricing](https://aws.amazon.com/cloudwatch/pricing/)).

**Paths A and B:** `agentcore deploy` turns it on for you after each deploy (a missing permission only logs a warning) and sets the X-Ray `Default` indexing rule to **100%**. To lower that, set `transactionSearchIndexPercentage` (or `"disableTransactionSearch": true`) in `~/.agentcore/config.json` — see [Transaction Search](https://github.com/aws/agentcore-cli/blob/main/docs/transaction_search.md) in the AgentCore CLI docs.

**Path C / IaC:** enable it yourself, once, with the console or Terraform.

**Console:** CloudWatch → Application Signals (APM) → Transaction Search → **Enable Transaction Search** → tick *Ingest spans as structured logs* → Save.

**Terraform:**

```hcl
data "aws_caller_identity" "current" {}
data "aws_region" "current" {}

locals {
  account = data.aws_caller_identity.current.account_id
  region  = data.aws_region.current.region # `.name` on AWS provider < 6.0
}

# Allow X-Ray to write spans into CloudWatch Logs
resource "aws_cloudwatch_log_resource_policy" "transaction_search" {
  policy_name = "TransactionSearchXRayAccess"
  policy_document = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Sid       = "TransactionSearchXRayAccess"
      Effect    = "Allow"
      Principal = { Service = "xray.amazonaws.com" }
      Action    = "logs:PutLogEvents"
      Resource = [
        "arn:aws:logs:${local.region}:${local.account}:log-group:aws/spans:*",
        "arn:aws:logs:${local.region}:${local.account}:log-group:/aws/application-signals/data:*",
      ]
      Condition = {
        ArnLike      = { "aws:SourceArn" = "arn:aws:xray:${local.region}:${local.account}:*" }
        StringEquals = { "aws:SourceAccount" = local.account }
      }
    }]
  })
}

# Send spans to CloudWatch Logs — this is the switch that enables Transaction Search
resource "aws_xray_trace_segment_destination" "this" {
  destination = "CloudWatchLogs"
  depends_on  = [aws_cloudwatch_log_resource_policy.transaction_search]
}
```

The setting is account-wide, so keep it in a shared bootstrap stack rather than per agent. Destroying these resources does not turn Transaction Search off. Verify with:

```bash
aws xray get-trace-segment-destination
# {"Destination": "CloudWatchLogs", "Status": "ACTIVE"}
```

Spans can take up to 10 minutes to appear after enabling.

---

## Where to Look

Open the agent's log group `/aws/bedrock-agentcore/runtimes/<agent_id>-<endpoint>` in [CloudWatch Logs](https://console.aws.amazon.com/cloudwatch/home#logsV2:log-groups), or use [Logs Insights](https://docs.aws.amazon.com/AmazonCloudWatch/latest/logs/AnalyzingLogData.html) on it. Agents created before their Region supported per-agent span delivery write spans to the shared `aws/spans` log group instead ([span destination](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/observability-configure.html#observability-configure-unified-traces)).

**Application logs:**

```
fields @timestamp, scope.name, severityText, body
| filter @logStream = "otel-rt-logs"
| sort @timestamp desc
```

**Token usage per model call:**

```
filter @logStream = "spans" and name like /^chat /
| fields @timestamp, attributes.session.id as session, attributes.gen_ai.request.model as model,
         attributes.gen_ai.usage.input_tokens as input_tokens, attributes.gen_ai.usage.output_tokens as output_tokens
| sort @timestamp desc
```

**Token usage per session:**

```
filter @logStream = "spans" and name like /^chat /
| stats sum(attributes.gen_ai.usage.input_tokens) as input_tokens,
        sum(attributes.gen_ai.usage.output_tokens) as output_tokens
  by attributes.session.id as session, attributes.gen_ai.request.model as model
```

The `chat <model-id>` span is the actual Bedrock call, so filtering on it counts each model call once. The `invoke_agent` span also carries `gen_ai.usage.*`, but those totals are **cumulative for the session**, not per turn.

For a visual view, open the [GenAI Observability dashboard](https://console.aws.amazon.com/cloudwatch/home#gen-ai-observability) → Bedrock AgentCore → **All sessions** or **All traces**, and pick a trace to see the span tree with tokens and latency.

## Cost

Spans carry token counts, not prices. For cost per session or trace, multiply the tokens above by the model's on-demand price from [Amazon Bedrock pricing](https://aws.amazon.com/bedrock/pricing/). For the billed amount, use [AWS Cost Explorer](https://console.aws.amazon.com/cost-management/home#/cost-explorer) filtered to Amazon Bedrock — it is per account and model, and usually lags up to 24 hours. AgentCore Runtime compute is billed separately from model tokens.

---

## Good to Know

- **Prompts and replies are logged.** Strands records model input and output on its spans, and ADOT copies them as `gen_ai.*` events into `otel-rt-logs`. To keep user content out of CloudWatch, set `OTEL_SEMCONV_STABILITY_OPT_IN=gen_ai_unredacted_attributes=` (Strands then writes `[REDACTED]`) and `OTEL_INSTRUMENTATION_GENAI_CAPTURE_MESSAGE_CONTENT=false` (botocore's `chat <model-id>` span) as environment variables on the agent runtime.
- **`logging.basicConfig()` is ignored in the cloud.** ADOT configures the root logger (at INFO) before `main.py` runs, so `basicConfig` becomes a no-op. Keep it if you want plain local output — it only matters when running without `opentelemetry-instrument`.
- **Read logs from `otel-rt-logs`.** The `[runtime-logs]` streams hold raw stdout/stderr and may be incomplete for invocation logs; the OTEL stream is the reliable source.
- **Local development is unchanged.** `sca dev` and `python main.py` run without `opentelemetry-instrument`, so nothing is exported.
- **Execution role.** ADOT writes with the runtime's execution role, which needs `logs:CreateLogStream` and `logs:PutLogEvents` on `/aws/bedrock-agentcore/runtimes/*`. Roles created by the AgentCore CLI or console include this; for your own IaC also grant `logs:PutResourcePolicy` on the agent's log group (needed to deliver spans there) and see the [execution role reference](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/runtime-permissions.html#runtime-permissions-execution).
- **Other observability backends.** Set `DISABLE_ADOT_OBSERVABILITY=true` on the runtime to drop AgentCore's default ADOT variables and configure your own exporter — see [Using other observability platforms](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/observability-configure.html#observability-configure-3p-platforms).

## Previous

[Chapter 09 — Deployment Strategies](Chapter_09.md)
