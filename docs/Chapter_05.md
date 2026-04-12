# Chapter 05 — The CLI

strands-compose-agentcore includes a CLI (`sca`) for local development and interactive testing.

```bash
sca <command> [options]
```

## Commands Overview

| Command | Purpose |
|---------|---------|
| `dev` | Start server + REPL in one terminal |
| `client local` | Interactive REPL connected to a local server |
| `client remote` | Interactive REPL connected to a deployed agent |

---

## `dev` — Local Development Server + REPL

Starts an HTTP server and an interactive REPL in the same terminal — the fastest way to iterate on your agent.

```bash
sca dev
sca dev --config path/to/config.yaml
sca dev --port 9090
sca dev --session-id my-session
```

The command creates the ASGI app with CORS enabled (`["*"]`) and the JSON log handler suppressed, then launches the server in a daemon thread and polls `GET /ping` (every 0.5 seconds, up to 30 seconds) until the server is healthy. Once ready, it opens the interactive REPL using a `LocalClient` connected to the server's `/invocations` endpoint. The REPL uses `AnsiRenderer` from strands-compose for colored, typewriter-style streaming output.

Because the server runs in a daemon thread within the same process, exiting the REPL terminates the server.

| Flag | Default | Description |
|------|---------|-------------|
| `--config` | `./config.yaml` | Path to strands-compose YAML config |
| `--port` | `8080` | Port for the HTTP server |
| `--session-id` | auto-generated | Session ID for the REPL |

If the port is already in use, the command exits with an error message suggesting `--port <number>`.

---

## `client` — Interactive REPL

Test agents interactively from the terminal. Both subcommands use the shared REPL loop with `AnsiRenderer` for colored streaming output.

### `client local`

Connect to a local server (started by `dev` or manually):

```bash
sca client local
sca client local --url http://localhost:9090/invocations
sca client local --session-id test-session
```

Under the hood, this creates a `LocalClient` — a sync HTTP client using `urllib` — and calls `.repl()`.

| Flag | Default | Description |
|------|---------|-------------|
| `--url` | `http://localhost:8080/invocations` | Server URL |
| `--session-id` | auto-generated | Session ID header value |

### `client remote`

Connect to a deployed [AgentCore Runtime](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/) agent:

```bash
# ARN is usually like: arn:aws:bedrock-agentcore:us-west-2:123456789012:runtime/my-agent-XXXXXXXXXX
sca client remote --arn <ARN>
sca client remote --arn <ARN> --region us-east-1
sca client remote --arn <ARN> --session-id my-session-id-at-least-33-characters-long
```

Under the hood, this creates an `AgentCoreClient` — an async boto3 wrapper — and calls `.repl()`. If no `--session-id` is provided, a random UUID-based ID (33+ characters, as required by AgentCore) is generated.

| Flag | Default | Description |
|------|---------|-------------|
| `--arn` | required | Full ARN of the deployed agent runtime |
| `--region` | boto3 default | AWS region override |
| `--session-id` | auto-generated UUID | Session ID (must be 33-256 chars for AgentCore) |

### REPL Commands

Inside the REPL:

| Command | Action |
|---------|--------|
| `/help` | Show available commands |
| `/clear` | Clear the terminal screen |
| `/session` | Show current session ID |
| `/exit` or `/quit` | Exit the REPL |
| Empty line | Exit the REPL |
| Ctrl-C | Exit the REPL |

---

## Why Our Own `dev` and `client` Commands?

The [AgentCore CLI](https://github.com/aws/agentcore-cli) provides its own `agentcore dev` and `agentcore invoke` commands. You might wonder why strands-compose-agentcore ships its own `dev` and `client` commands instead of using those.

The reason is **event formatting**. strands-compose agents stream structured JSON `StreamEvent` objects (tokens, tool calls, handoffs, completions) via Server-Sent Events. The AgentCore CLI's built-in commands treat the response as plain text — they cannot parse or render these structured events. As a result:

- **`agentcore dev`** starts the server correctly, but the built-in REPL cannot display streaming events with colored output, typewriter effects, or structured tool/handoff rendering. You see raw JSON lines instead of a readable conversation.
- **`agentcore invoke`** sends a prompt to a deployed agent, but again renders the SSE response as raw text rather than interpreting event types.

Our `sca dev` and `sca client` commands use `AnsiRenderer` from strands-compose to render events with color, formatting, and progressive typewriter output — the same rendering you get when running strands-compose agents locally. This is why we recommend using our CLI tools for both local development and deployed agent interaction.

> **Recommendation:** Use `sca dev` for local development and `sca client remote` for deployed agents. Use `agentcore dev` and `agentcore invoke` only if you need raw unformatted output or are debugging wire-level SSE issues.

## Next

[Chapter 06 — Deployment](Chapter_06.md)
