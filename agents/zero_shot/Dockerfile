# Cloud Run image for the Zero-shot Predictor A2A agent.
# Cloud Run injects $PORT (defaults to 8080); uvicorn binds to it.
#
# Build + deploy via `make deploy-zero-shot`. The build context is the repo
# root (not `agents/zero_shot/`), so the COPY paths below are repo-rooted.
# The agent talks to the MCP over HTTP — so it does NOT bundle `mcp_server/`,
# `services/`, or `schemas/`; only `agents/__init__.py` (the package-level
# GCP-auth bootstrap) and the zero-shot code itself.

FROM python:3.13-slim

# uv for fast, reproducible installs from uv.lock.
RUN pip install --no-cache-dir uv

WORKDIR /app

# Install dependencies first (cached layer — only re-runs when pyproject/uv.lock change).
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-install-project

# Copy only the runtime sources this agent needs.
COPY agents/__init__.py ./agents/__init__.py
COPY agents/zero_shot/ ./agents/zero_shot/

# Final sync — installs the project itself now that the package code is present.
RUN uv sync --frozen

ENV PORT=8080
EXPOSE 8080

CMD uv run uvicorn agents.zero_shot.agent:a2a_app --host 0.0.0.0 --port ${PORT}
