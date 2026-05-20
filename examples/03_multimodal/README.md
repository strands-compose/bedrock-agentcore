# 03 — Multimodal Payloads

> Send images and documents to your agent over the SSE wire.

## What this shows

- A single vision-capable agent that accepts text, images, and documents
- The single multimodal payload shape accepted by `/invocations`:
  the `prompt` key with a string, a single content block, or a list of blocks
- The `image()`, `document()`, `text()`, and `reply()` builders in `strands_compose_agentcore.media`
- Server-side base64 decoding (`source.base64` → `source.bytes`)
- Size limits (`max_payload_bytes`, `max_media_bytes`, `max_media_blocks`)

## Files

| File | Purpose |
|------|---------|
| `config.yaml` | One vision-capable agent (Claude Sonnet) |
| `main.py` | Entry script — wraps the config as a `BedrockAgentCoreApp` |
| `client.py` | Sends `[image(...), text(...), document(...)]` to the local server |

## Prerequisites

- AWS credentials configured (`aws configure` or environment variables)
- Vision-capable Bedrock model access (Anthropic Claude or similar)
- Dependencies installed: `pip install strands-compose-agentcore`

## Run

```bash
# Terminal 1 — start the local server
python examples/03_multimodal/main.py

# Terminal 2 — send an image + a question
python examples/03_multimodal/client.py "What is in this image and document about?"
```

## Payload shapes

The `/invocations` endpoint accepts a single top-level key, `prompt`, whose value mirrors `strands.Agent.__call__` input:

```jsonc
{ "prompt": "Hello" }
{ "prompt": {"text": "Describe"} }
{ "prompt":
  [
    {"image": {"format": "png", "source": {"base64": "..."}}},
    {"document": {"format": "pdf", "name": "report", "source": {"base64": "..."}}},
    {"text": "Summarise the image and the document."}
  ]
}
```

Inside any media `source`, use **`base64`** for inline bytes (the
server decodes it to native `bytes`).

## Caveat: delegate sub-agents

Delegate tools and sub-agents in `strands-compose` orchestrations accept text input only.

To use multimodal input today, set `entry: <single_agent_name>` (as this example does).
