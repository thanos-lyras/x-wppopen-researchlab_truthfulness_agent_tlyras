"""Module-level Vertex-mode genai client shared across services and MCP tools.

Pinned to a regional `LOCATION` (us-central1 by default) — required for both
tuned-endpoint inference and SFT job submission. Base-model calls (e.g. zero-shot
gemini-2.5-flash) work in any region; the regional pin doesn't hurt them.
"""

from google import genai

from mcp_server.utils import config

client = genai.Client(
    vertexai=True, project=config.PROJECT_ID, location=config.LOCATION
)
