# Cloud Run image for the Orchestrator A2A agent. Build context = repo root.

FROM python:3.13-slim

RUN pip install --no-cache-dir uv
WORKDIR /app

# Deps first — cached layer keyed to pyproject.toml / uv.lock.
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-install-project

# Orchestrator code + only the sub-agents' client.py wrappers (RemoteA2aAgent).
# Sub-agents' agent.py / tools.py / prompt.py run in their own images.
COPY agents/__init__.py agents/agent.py agents/prompt.py ./agents/
COPY agents/explainer/__init__.py agents/explainer/client.py ./agents/explainer/
COPY agents/fine_tuned/__init__.py agents/fine_tuned/client.py ./agents/fine_tuned/
COPY agents/zero_shot/__init__.py agents/zero_shot/client.py ./agents/zero_shot/

# /invoke uploads to GCS via GCSService; schemas for future server-side validation.
COPY services/ ./services/
COPY schemas/ ./schemas/

RUN uv sync --frozen

ENV PORT=8080
EXPOSE 8080
CMD uv run uvicorn agents.agent:a2a_app --host 0.0.0.0 --port ${PORT}
