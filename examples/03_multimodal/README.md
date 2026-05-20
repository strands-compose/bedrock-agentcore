# 03 — Multimodal Payloads

> Send images and documents to your agent over the SSE wire.

## What this shows

- A single vision-capable agent that accepts text **and** images
- The three multimodal payload shapes accepted by `/invocations`:
  `prompt` (string), `content` (single user turn), `messages` (full
  conversation)
- The `image_block`, `document_block`, `s3_image_block` and
  `s3_document_block` builders in `strands_compose_agentcore.media`
- Server-side base64 decoding (`source.base64` → `source.bytes`)
- Size limits (`max_payload_bytes`, `max_media_bytes`, `max_media_blocks`)

## Files

| File | Purpose |
|------|---------|
| `config.yaml` | One vision-capable agent (Claude Sonnet) |
| `main.py` | Entry script — wraps the config as a `BedrockAgentCoreApp` |
| `client.py` | Sends `[image_block(...), {"text": "..."}]` to the local server |

## Prerequisites

- AWS credentials configured (`aws configure` or environment variables)
- Vision-capable Bedrock model access (Anthropic Claude or similar)
- Dependencies installed: `pip install strands-compose-agentcore`

## Run

```bash
# Terminal 1 — start the local server
python examples/03_multimodal/main.py

# Terminal 2 — send an image + a question
python examples/03_multimodal/client.py path/to/cat.png "What is in this image?"
```

## Payload shapes

The `/invocations` endpoint accepts **exactly one** of three keys.

```jsonc
{ "prompt": "Hello" }                                                  // back-compat
{ "content": [ {"image": {"format": "png",
                          "source": {"base64": "..."}}},
               {"text": "Describe"} ] }                                // single turn
{ "messages": [ {"role": "user", "content": [...]} ] }                 // conversation
```

Inside any media `source`, use **`base64`** for inline bytes (the
server decodes it to native `bytes`) or **`location`** for an S3 URI
(passed through unchanged).

## Caveat: delegate sub-agents

Delegate tools and sub-agents in `strands-compose` orchestrations
accept text input only.  To use multimodal input today, set
`entry: <single_agent_name>` (as this example does).  Multi-agent
entries (`Swarm`, `Graph`) accept `prompt` or `content`, but not
full `messages` conversations.
