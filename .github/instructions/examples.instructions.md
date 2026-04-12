---
applyTo: "examples/**/*.py,examples/**/*.yaml"
---

# Example Code Instructions

Examples must be complete, easy to understand, and self-contained where runnable.

- Runnable example directories need `config.yaml`, `main.py`, `pyproject.toml`, and `README.md`.
- Python files must be runnable as-is with `python examples/NN_name/main.py`.
- YAML files must use valid strands-compose syntax.
- Use bare `python` and `pip` in all command examples — examples target end users, not package developers.
- Keep examples minimal — demonstrate one concept per example.
- Do not import private/internal APIs — only use the public API from `strands_compose_agentcore`.
