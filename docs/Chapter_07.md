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

for event in client.invoke(prompt="Hello"):
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
    session_id="a" * 33,  # 33+ chars required
    prompt="Hello!",
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

### Session ID Requirements

AgentCore requires session IDs of 33–256 characters. The `AgentCoreClient` enforces both bounds and raises `ValueError` for IDs outside this range. When using the REPL without specifying a session ID, a random UUID-based ID (33+ characters) is generated automatically.

### invoke() Parameters

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `session_id` | `str` | required | AgentCore session ID (33-256 chars) |
| `prompt` | `str` | required | User message |
| `payload_extras` | `dict \| None` | `None` | Additional keys merged into the JSON payload |

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
    async for event in client.invoke(session_id="a" * 33, prompt="Hello"):
        print(event.type, event.data)
# thread pool is shut down automatically
```

You can also call `client.close()` manually when the client is no longer needed. In-flight streams finish before the pool is torn down.

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
        session_id=session_id,
        prompt=prompt,
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
            session_id=session_id,
            prompt=prompt,
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
    async for event in client.invoke(session_id=session_id, prompt=prompt):
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
    async for event in client.invoke(session_id=session_id, prompt=prompt):
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
