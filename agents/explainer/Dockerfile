# Cloud Run image for the Explainer A2A agent. Build context = repo root.

FROM python:3.13-slim

RUN pip install --no-cache-dir uv
WORKDIR /app

# Deps first — cached layer keyed to pyproject.toml / uv.lock.
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-install-project

COPY agents/__init__.py ./agents/__init__.py
COPY agents/explainer/ ./agents/explainer/

RUN uv sync --frozen

ENV PORT=8080
EXPOSE 8080
CMD uv run uvicorn agents.explainer.agent:a2a_app --host 0.0.0.0 --port ${PORT}
