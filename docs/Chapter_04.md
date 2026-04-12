# Chapter 04 — Session & Streaming

## How AgentCore Runtime Works

When you deploy an agent with `agentcore deploy`, AWS provisions a managed compute environment for it. Unlike traditional container hosting (ECS, Lambda), [AgentCore Runtime](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/) is purpose-built for AI agents. Each active session gets its own isolated microVM — a lightweight virtual machine that runs your Python code. You never manage servers, containers, or scaling rules.

Here is what happens when a client invokes your deployed agent:

1. **Routing** — AgentCore receives the request and reads the `X-Amzn-Bedrock-AgentCore-Runtime-Session-Id` header
2. **Session affinity** — if a microVM already exists for that session ID, the request is routed there. If not, a new microVM is created
3. **Cold start** — the microVM imports your entry module, finds the `app` variable, and starts the ASGI server on port 8080
4. **Invocation** — the request hits `POST /invocations`, your agent processes it, and events stream back via SSE
5. **Idle timeout** — after a configurable period of inactivity (default: 15 minutes), the microVM is shut down

This architecture means there is no cross-session state: two different session IDs never share memory. Within a session however, your agents retain their full conversation history because the same Python process handles all requests. AWS creates and destroys microVMs based on demand, and AgentCore polls `GET /ping` to monitor health — `BedrockAgentCoreApp` handles this automatically, reporting `HEALTHY` or `HEALTHY_BUSY`.

## Session Lifecycle

A session represents a single conversation with preserved agent state. The lifecycle mirrors the two-phase resolution described in [Chapter 03](Chapter_03.md):

1. **First request arrives** — the app reads the session ID from the runtime header
2. **Session resolves** — `load_session()` creates agents, orchestrations, and the entry point
3. **Event queue wires up** — `resolved.wire_event_queue()` connects all agents to a shared `EventQueue` for streaming
4. **Cached** — the `SessionState` is stored in `app.state.session` for reuse
5. **Follow-up requests** — same session ID reuses the cached agents and conversation history. The event queue is flushed between turns to discard stale events
6. **New session ID** — the old session is discarded and fresh agents are created

The `SessionState` dataclass holds everything needed for a session:

```python
@dataclass
class SessionState:
    resolved: ResolvedConfig       # Agents, orchestrations, entry point
    events: EventQueue             # Shared event queue for streaming
    invocation_lock: asyncio.Lock  # Prevents concurrent invocations
```

## Streaming

Agent invocations produce a stream of `StreamEvent` objects delivered as Server-Sent Events (SSE). When the entry agent is invoked, it runs asynchronously in a background task. As the agent thinks, calls tools, and generates text, events are pushed to the `EventQueue`. The main coroutine drains this queue and yields events to the HTTP response.

```
Entry Agent (async task)
    ↓ pushes events
EventQueue
    ↓ drained by
/invocations response (SSE)
    ↓ received by
Client (LocalClient or AgentCoreClient)
```

Between turns, the event queue is flushed to discard any stale events from the previous invocation.

### Event Types

Events are `StreamEvent` objects defined by [strands-compose](https://github.com/strands-compose/sdk-python). Each event carries a `type`, the `agent_name` that produced it, a UTC `timestamp`, and a type-specific `data` dict.

**Single-agent events:**

| Type | Description |
|------|-------------|
| `agent_start` | Agent began processing |
| `token` | A chunk of generated text |
| `tool_start` | Agent is calling a tool |
| `tool_end` | Tool returned a result |
| `reasoning` | Model's reasoning/thinking output |
| `complete` | Agent finished processing |
| `error` | Something went wrong |

**Multi-agent events** (orchestrations):

| Type | Description |
|------|-------------|
| `node_start` | A node in the orchestration started |
| `node_stop` | A node in the orchestration stopped |
| `handoff` | Agent handing off to another agent |
| `multiagent_start` | Multi-agent orchestration started |
| `multiagent_complete` | Multi-agent orchestration finished |

### Error Handling

If the agent raises an exception during invocation, the error is logged, an `error` event with `{"message": "internal error during agent invocation"}` is pushed to the queue, and the queue is closed. The server does not crash — it remains ready for the next invocation.

## Concurrency

Only one invocation can run at a time per session. This is enforced by an `asyncio.Lock` on the `SessionState`. If a second request arrives while the first is still running, the server returns an error event (`"agent is already running, try again later"`) and reports `HEALTHY_BUSY` on `/ping` so AgentCore Runtime can back off. The lock is released when the invocation completes, whether it succeeds or fails.

On AgentCore Runtime, each session gets its own microVM, so there is no cross-session concurrency within a single app instance. If a request arrives with a different session ID while the server is idle, the old session is discarded and a new one is created — this is expected behavior for the one-microVM-per-session model.

## Conversation Persistence

By default, conversation history lives only in memory. The strands `Agent` keeps messages in its internal state, so follow-up prompts within the same process see the full conversation. But when the process restarts — or when a microVM is recycled after the idle timeout — that history is gone.

To persist conversations across restarts, configure a `session_manager` in your YAML. The session manager is a strands concept: it hooks into the agent lifecycle to save and restore messages. strands-compose resolves the provider you specify and passes it to every agent it creates.

### Available Providers

| Provider | Backend | Persistence | Use Case |
|----------|---------|-------------|----------|
| *(none)* | In-memory | Lost on restart | Local development, stateless agents |
| `file` | Local filesystem | Survives restarts, not deployments | Local development with history |
| `s3` | [Amazon S3](https://docs.aws.amazon.com/s3/) | Survives deployments | Production persistence without memory features |
| `agentcore` | [Bedrock AgentCore Memory](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/) | Survives deployments | Production persistence with long-term memory |

The `file` and `s3` providers are straightforward key-value stores: they serialize the full agent state (session metadata and all messages) as JSON and save it under a path derived from the session ID and agent name. On restore, they load that JSON back into the agent.

### The `agentcore` Provider

The `agentcore` provider is fundamentally different from `file` and `s3`. It is not just a persistence backend — it is an integration with [Bedrock AgentCore Memory](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/), a managed memory service that goes beyond simple message storage. The implementation lives in the `bedrock-agentcore` package as `AgentCoreMemorySessionManager`.

The provider persists messages as immutable events in AgentCore Memory, organized by session and agent. Unlike the file/S3 providers which store a single JSON blob, AgentCore Memory treats each message as a separate event — this enables semantic retrieval, batching, and long-term memory strategies.

Key capabilities that differentiate it:

- **Short-term memory (STM)** — within a session, messages are stored and restored like the other providers, preserving conversation history across process restarts
- **Long-term memory (LTM)** — across sessions, AgentCore Memory can retrieve relevant memories from configurable namespaces using semantic search and inject them as context into new conversations. This means your agent can "remember" information from past sessions
- **Batching** — messages can be batched before sending to the Memory API for efficiency (`batch_size` parameter)
- **Persistence modes** — `FULL` persists everything, `NONE` keeps messages local-only but still allows LTM retrieval from previously stored data

#### Configuration

```yaml
session_manager:
  provider: agentcore
  params:
    memory_id: "mem-abc123"          # Required: Bedrock AgentCore Memory ID
    actor_id: "my_agent"             # Required: unique agent/user identifier
```

The `memory_id` is the identifier of your Bedrock AgentCore Memory resource (created via the AWS console or API). The `actor_id` is a unique identifier for the agent instance — it is recommended to use your agent name.

For long-term memory with semantic retrieval:

```yaml
session_manager:
  provider: agentcore
  params:
    memory_id: "mem-abc123"
    actor_id: "my_agent"
    retrieval_config:
      "/preferences/{actorId}/":     # Namespace for user preferences
        top_k: 10
        relevance_score: 0.7
      "/facts/{actorId}/":           # Namespace for general facts
        top_k: 5
        relevance_score: 0.3
    batch_size: 5                    # Batch messages before sending
    flush_interval_seconds: 30       # Auto-flush interval
```

When retrieval is configured, the session manager automatically queries AgentCore Memory for relevant past interactions and injects them as context into the conversation before the agent processes each turn.

> For more details on AgentCore Memory, see the [AgentCore Memory documentation](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/).

## Next

[Chapter 05 — The CLI](Chapter_05.md)
