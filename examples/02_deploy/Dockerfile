# --- Stage 1: build dependencies ---
FROM ghcr.io/astral-sh/uv:python3.12-trixie-slim AS builder

WORKDIR /app

ENV UV_COMPILE_BYTECODE=1 \
    UV_NO_PROGRESS=1

COPY pyproject.toml ./
RUN uv sync --no-cache --no-dev --no-install-project

# --- Stage 2: runtime ---
FROM python:3.12-slim-trixie

WORKDIR /app

ENV PYTHONUNBUFFERED=1 \
    DOCKER_CONTAINER=1 \
    PATH="/app/.venv/bin:$PATH"

RUN useradd -m -u 1000 bedrock_agentcore

COPY --from=builder /app/.venv /app/.venv
COPY --chown=bedrock_agentcore:bedrock_agentcore . .

USER bedrock_agentcore

EXPOSE 8080

CMD ["opentelemetry-instrument", "python", "main.py"]
