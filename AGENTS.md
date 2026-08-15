# strands-compose-agentcore -- Agent Instructions

A **thin deployment adapter** that bridges strands-compose YAML configs to AWS
Bedrock AgentCore Runtime. It validates the config once at boot, builds agents
lazily per session, streams events via SSE, and provides a client trio for
invoking deployed or local agents.

---

## Mental Model

1. **strands-compose-first** -- resolution, streaming, rendering, and config parsing live upstream. Use them; never re-implement.
2. **Config at boot, session per invocation** -- `load_config` validates once in the factory; `resolve_session` calls `load(app_config, session_id=…)` on the first request (cached until a new ID arrives). A replaced session is closed first via `close_session`, so a delegated agent's MCP subprocess cannot outlive it.
3. **Server vs client** -- the server runs inside the AgentCore pod (`app.py`, `session.py`, `payload.py`); clients run outside (`client/`). They share only the wire contract (`{"prompt": ...}` + SSE `StreamEvent` dicts).
4. **Single source of truth for formats** -- `MEDIA_FORMATS` in `media_formats.py`; everything else derives from it.
5. **Typed exception hierarchy** -- every AWS error code maps to an `AgentCoreClientError` subclass.
6. **Smallest reasonable change** -- don't refactor unrelated code.

---

## Verify

```bash
uv run just check    # ruff format-check + ruff lint + ty type-check + bandit
uv run just test     # pytest --numprocesses=2 --cov --cov-fail-under=80
uv run just format   # auto-format (run before check if lint fails)
```

---

## Detailed Guidance

For comprehensive development and testing rules, load the `.kiro/skills/`:

| Skill | Purpose |
|-------|---------|
| `.kiro/skills/library-development/SKILL.md` | Architecture, conventions, module roles, adding features |
| `.kiro/skills/library-development/references/project-map.md` | File tree, "read first" table, invariants, public API |
| `.kiro/skills/library-testing/SKILL.md` | Testing doctrine: what to test, what not to, mocking policy |
| `.kiro/skills/library-testing/references/test-patterns.md` | Copy-paste templates: fakes, builders, test shapes |

---

## Key Imports

```python
from strands_compose import load, load_config
from strands_compose import AppConfig, ResolvedConfig
from strands_compose import EventQueue, StreamEvent, AnsiRenderer
from strands_compose import make_event_queue, serialize_multiagent_result
from bedrock_agentcore import BedrockAgentCoreApp
from bedrock_agentcore.runtime.context import BedrockAgentCoreContext
```

Two deep imports are sanctioned because strands-compose does not surface them at
top level; both are confined to `session.py`:

```python
from strands_compose.manifest import build_manifest
from strands_compose.types import SessionManifest
```

---

## Non-Negotiable Code Rules

- `from __future__ import annotations` in every module
- Fully typed signatures; `X | None` not `Optional`
- Google-style docstrings; class docs on `__init__` (except `@dataclass`)
- `logging.getLogger(__name__)` with `%s` interpolation and `key=<value> | message` format
- `print()` only for CLI/REPL user output
- Early returns; max 3 nesting levels
- Specific exceptions with context; never bare `except:`
- No `eval`/`exec`/`pickle` on untrusted data; no hardcoded secrets
