# Cloud Run image for the truthfulness MCP server. Build context = repo root.

FROM python:3.13-slim

RUN pip install --no-cache-dir uv
WORKDIR /app

# Deps first — cached layer keyed to pyproject.toml / uv.lock.
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-install-project

COPY mcp_server/ ./mcp_server/
COPY services/ ./services/
COPY schemas/ ./schemas/

RUN uv sync --frozen

ENV PORT=8080
EXPOSE 8080
CMD uv run uvicorn mcp_server.server:app --host 0.0.0.0 --port ${PORT}
