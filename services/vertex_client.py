"""Module-level Vertex-mode genai client shared across services and MCP tools.

Pinning to `TUNING_LOCATION` (regional) is required for tuned-endpoint inference;
base-model calls (e.g. zero-shot gemini-2.5-flash) work identically in any region.
"""

from google import genai

from mcp_server.utils import config

client = genai.Client(
    vertexai=True, project=config.PROJECT_ID, location=config.TUNING_LOCATION
)
