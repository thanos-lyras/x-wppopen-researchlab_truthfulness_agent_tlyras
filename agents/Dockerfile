# Cloud Run image for the Orchestrator A2A agent.
# Cloud Run injects $PORT (defaults to 8080); uvicorn binds to it.
#
# Build + deploy via `make deploy-orchestrator`. The build context is the repo
# root, so the COPY paths below are repo-rooted. The orchestrator imports the
# `client.py` modules of the three sub-agents (RemoteA2aAgent wrappers); each
# sub-agent's `*_A2A_URL` env var must be set at runtime so those clients point
# at the deployed Cloud Run services rather than localhost.

FROM python:3.13-slim

# uv for fast, reproducible installs from uv.lock.
RUN pip install --no-cache-dir uv

WORKDIR /app

# Install dependencies first (cached layer — only re-runs when pyproject/uv.lock change).
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-install-project

# Orchestrator code (agent.py, prompt.py) + sub-agent client modules.
# We need each sub-agent's __init__.py + client.py so the orchestrator can
# `from agents.<name>.client import <name>_remote_agent`. We do NOT need the
# sub-agents' agent.py / tools.py / prompt.py — those run in their own images.
COPY agents/__init__.py agents/agent.py agents/prompt.py ./agents/
COPY agents/explainer/__init__.py agents/explainer/client.py ./agents/explainer/
COPY agents/fine_tuned/__init__.py agents/fine_tuned/client.py ./agents/fine_tuned/
COPY agents/zero_shot/__init__.py agents/zero_shot/client.py ./agents/zero_shot/

# /predict and /explain REST handlers upload the request body to GCS and
# validate it as a JSON shape — needs the GCSService wrapper and (for future
# server-side Pydantic validation) the schemas package.
COPY services/ ./services/
COPY schemas/ ./schemas/

# Final sync — installs the project itself now that the package code is present.
RUN uv sync --frozen

ENV PORT=8080
EXPOSE 8080

CMD uv run uvicorn agents.agent:a2a_app --host 0.0.0.0 --port ${PORT}
