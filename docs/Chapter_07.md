# Chapter 07 — The Client

strands-compose-agentcore provides two client classes for invoking agents programmatically and a shared REPL for interactive testing. The clients are designed for different contexts — `LocalClient` for local development and `AgentCoreClient` for deployed agents — but both expose the same streaming interface: iterate over `StreamEvent` objects as the agent produces them.

| Client | Use Case | Transport | Sync/Async |
|--------|----------|-----------|------------|
| `LocalClient` | Local development | HTTP (urllib) | Sync |
| `AgentCoreClient` | Deployed agents on [AgentCore Runtime](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/) | [boto3](https://pypi.org/project/boto3/) (AgentCore API) | Async |

---

## LocalClient

A lightweight sync client for the local development server. No async, no boto3, no extra dependencies — just `urllib`. Events stream in real-time: each SSE line is yielded as soon as it arrives from the socket, so callers see tokens appearing progressively.

### Usage

```python
from strands_compose_agentcore import LocalClient

client = LocalClient(
    url="http://localhost:8080/invocations",                # default
    session_id="default-session-strands-compose-agentcore",   # default
)

for event in client.invoke("Hello"):
    print(event.type, event.data)
```

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `url` | `str` | `http://localhost:8080/invocations` | URL of the `/invocations` endpoint |
| `session_id` | `str \| None` | `DEFAULT_SESSION_ID` | Session ID sent in the AgentCore header |

The `invoke()` method returns a `Generator[StreamEvent, None, None]`. Pass `session_id` to override the default for a single call. Raises `ClientConnectionError` if the server is unreachable.

```python
client.repl()                          # interactive REPL with colored streaming
client.repl(session_id="custom")       # override session ID
```

---

## AgentCoreClient

An async wrapper around boto3's `invoke_agent_runtime` for invoking deployed agents on AgentCore Runtime. Each `invoke()` call gets its own boto3 streaming response — no shared mutable state between sessions. A dedicated `ThreadPoolExecutor` (sized by `max_concurrent_streams`) offloads blocking I/O so the asyncio event loop is never starved.

### Usage

```python
from strands_compose_agentcore import AgentCoreClient

client = AgentCoreClient(
    "arn:aws:bedrock-agentcore:us-west-2:123456789012:runtime/my-agent-XXXXXXXXXX",
    region="us-west-2",
)

async for event in client.invoke(
    "Hello!",
    session_id="a" * 33,  # 33+ chars required
):
    print(event.type, event.data)
```

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `agent_runtime_arn` | `str` | required | Full ARN of the deployed agent runtime |
| `region` | `str \| None` | boto3 default | AWS region override |
| `session` | `boto3.Session \| None` | `None` | Pre-configured boto3 session |
| `timeout` | `float \| None` | `None` | Socket read timeout in seconds |
| `max_concurrent_streams` | `int` | `64` | Max concurrent `invoke()` calls |
| `retry` | `RetryConfig \| None` | `None` | Retry config for throttled requests. `None` disables retry. Pass `RetryConfig()` for sensible defaults |

### Session ID Requirements

AgentCore requires session IDs of 33–256 characters. The `AgentCoreClient` enforces both bounds and raises `ValueError` for IDs outside this range. When using the REPL without specifying a session ID, the fixed default `"default-session-strands-compose-agentcore"` is used.

### invoke() Parameters

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `agent_input` | `str \| ContentBlock \| list[ContentBlock]` | required | User turn: plain string, one content block, or a list of blocks |
| `session_id` | `str` | required (keyword-only) | AgentCore session ID (33-256 chars) |

Returns an `AsyncGenerator[StreamEvent, None]`.

### Errors

| Exception | Cause |
|-----------|-------|
| `ValueError` | Session ID shorter than 33 or longer than 256 characters |
| `ClientConnectionError` | Cannot reach the agent server (local or remote) |
| `AccessDeniedError` | Credentials lack `bedrock-agentcore:InvokeAgentRuntime` permission |
| `ThrottledError` | Request was rate-limited |
| `AgentCoreClientError` | Any other service error |

All client exceptions inherit from `AgentCoreClientError`:

```python
from strands_compose_agentcore import (
    AgentCoreClientError,      # Base exception
    ClientConnectionError,     # Cannot reach agent
    AccessDeniedError,         # IAM permission issue
    ThrottledError,            # Rate limited
)
```

### Cleanup

`AgentCoreClient` supports `async with` for automatic cleanup:

```python
async with AgentCoreClient(ARN, region="us-west-2") as client:
    async for event in client.invoke("Hello", session_id="a" * 33):
        print(event.type, event.data)
# thread pool is shut down automatically
```

You can also call `client.close()` manually when the client is no longer needed. In-flight streams finish before the pool is torn down.

### Session lifecycle and the AgentCore Runtime control plane

When you call `client.invoke(...)`, the request travels through the following chain:

**HTTP client → AgentCore Runtime control plane → microVM pod → asyncio event loop → strands entry agent**

The [AgentCore Runtime](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/runtime-overview.html) control plane routes each request to the microVM pod assigned to the session, where the strands entry agent runs inside an asyncio event loop. The control plane acts as a one-way bridge: it forwards the request into the pod but does **not** propagate a client TCP disconnect back into the pod. If the HTTP client closes the connection mid-stream (browser tab closed, proxy timeout, `aclose()` on the generator), the agent inside the pod continues running to completion, S3 session state is fully persisted, and `/ping` reports `HEALTHY_BUSY` until the agent finishes.

This means local asyncio cancellation machinery (the `task.cancel()` path in `invoke`) is dead code under the AgentCore Runtime disconnect path — the worker loop never sees the consumer-side abort.

The only AWS-documented mechanism to terminate a running session from outside the pod is the [`StopRuntimeSession` API](https://docs.aws.amazon.com/bedrock-agentcore/latest/APIReference/API_StopRuntimeSession.html), exposed on `AgentCoreClient` as `stop_session()`. See the [`stop_session()`](#stop_session) subsection below.

### stop_session()

Stop a deployed AgentCore runtime session. AWS documents this as instantly terminating the specified session and stopping any ongoing streaming responses.

```python
from strands_compose_agentcore import AgentCoreClient

client = AgentCoreClient(
    "arn:aws:bedrock-agentcore:us-west-2:123456789012:runtime/my-agent-XXXXXXXXXX",
    region="us-west-2",
)

result = await client.stop_session("a" * 33)
print(result.runtime_session_id, result.status_code)
```

#### Parameters

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `session_id` | `str` | required | AgentCore session ID (33–256 chars) |
| `qualifier` | `str \| None` | `None` | Endpoint alias (e.g. `"prod"`). When `None`, AWS uses `DEFAULT` |
| `client_token` | `str \| None` | `None` | Idempotency token. When `None`, boto3 auto-populates one |

Returns a `StopSessionResult` with `runtime_session_id: str` and `status_code: int`.

#### Errors

| Exception | Cause |
|-----------|-------|
| `ValueError` | Session ID shorter than 33 or longer than 256 characters |
| `AccessDeniedError` | Caller lacks `bedrock-agentcore:StopRuntimeSession` permission |
| `ThrottledError` | Request was rate-limited |
| `SessionNotFoundError` | Session not found or already terminated |
| `InvalidRequestError` | ARN, session ID, or client token failed service-side validation |
| `ConflictError` | Session is in an incompatible state |
| `RetryableConflictError` | Transient conflict; retry with exponential backoff |
| `AgentCoreClientError` | Any other service error |

#### Graceful shutdown timing

AWS documents that termination can take [up to 15 seconds for graceful shutdown](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/runtime-stop-session.html). The `stop_session()` call returns as soon as the [StopRuntimeSession](https://docs.aws.amazon.com/bedrock-agentcore/latest/APIReference/API_StopRuntimeSession.html) API accepts the request — the session may still be winding down for a short window after the call returns. If you need to confirm the session is fully gone before proceeding, poll the session status or wait for the in-flight `invoke()` stream to end.

#### Idempotency

Re-using the same `client_token` for the same session and ARN returns success without re-acting — boto3 handles this transparently and `stop_session()` returns a `StopSessionResult` reflecting the original successful response. If the session has already been terminated, AWS returns `ResourceNotFoundException`, which surfaces as `SessionNotFoundError`. Treat `SessionNotFoundError` as "already stopped, no further action needed":

```python
from strands_compose_agentcore import SessionNotFoundError

try:
    await client.stop_session(session_id)
except SessionNotFoundError:
    pass  # already stopped — nothing to do
```

#### IAM permissions

The calling principal requires `bedrock-agentcore:StopRuntimeSession` on the target runtime ARN:

```json
{
  "Effect": "Allow",
  "Action": "bedrock-agentcore:StopRuntimeSession",
  "Resource": "arn:aws:bedrock-agentcore:us-west-2:123456789012:runtime/my-agent-XXXXXXXXXX"
}
```

This permission is **not** included in the default AgentCore Runtime execution role used by the pod itself. If you call `stop_session()` from inside the pod, you must attach an explicit IAM policy to the pod's execution role. Typically this permission belongs to the proxy, backend service, or operator tooling that fronts the deployed agent — not the agent pod itself.

---

## Integration Patterns

### FastAPI

```python
from contextlib import asynccontextmanager
from fastapi import FastAPI
from strands_compose_agentcore import AgentCoreClient

ARN = "arn:aws:bedrock-agentcore:us-west-2:123456789012:runtime/my-agent-XXXXXXXXXX"

@asynccontextmanager
async def lifespan(app):
    async with AgentCoreClient(ARN, region="us-west-2") as client:
        app.state.agent = client
        yield

app = FastAPI(lifespan=lifespan)

@app.post("/chat")
async def chat(prompt: str, session_id: str):
    events = []
    async for event in app.state.agent.invoke(
        prompt,
        session_id=session_id,
    ):
        events.append(event.asdict())
    return {"events": events}
```

### FastAPI with SSE Forwarding

```python
from fastapi import FastAPI
from fastapi.responses import StreamingResponse
from strands_compose_agentcore import AgentCoreClient
import json

@app.post("/stream")
async def stream(prompt: str, session_id: str):
    async def generate():
        async for event in app.state.agent.invoke(
            prompt,
            session_id=session_id,
        ):
            yield f"data: {json.dumps(event.asdict())}\n\n"

    return StreamingResponse(generate(), media_type="text/event-stream")
```

### AWS Lambda

```python
import asyncio
import json
from strands_compose_agentcore import AgentCoreClient

client = AgentCoreClient(
    "arn:aws:bedrock-agentcore:us-west-2:123456789012:runtime/my-agent-XXXXXXXXXX",
    region="us-west-2",
)

def handler(event, context):
    prompt = event.get("prompt", "")
    session_id = event.get("session_id", "a" * 33)

    events = asyncio.run(collect_events(prompt, session_id))
    return {"statusCode": 200, "body": json.dumps(events)}

async def collect_events(prompt, session_id):
    result = []
    async for event in client.invoke(prompt, session_id=session_id):
        result.append(event.asdict())
    return result
```

### Batch Processing

```python
import asyncio
from strands_compose_agentcore import AgentCoreClient

client = AgentCoreClient(ARN, region="us-west-2")

async def process_prompt(session_id: str, prompt: str) -> list:
    events = []
    async for event in client.invoke(prompt, session_id=session_id):
        if event.type == "text":
            events.append(event.data.get("text", ""))
    return events

async def main():
    tasks = [
        process_prompt(f"session-{'x' * 30}-{i}", f"Summarize topic {i}")
        for i in range(10)
    ]
    results = await asyncio.gather(*tasks)
    for i, result in enumerate(results):
        print(f"Topic {i}: {''.join(result)}")

asyncio.run(main())
```

## Next

[Chapter 08 — Advanced Topics](Chapter_08.md)
