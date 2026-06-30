"""Tool manifest for the Explainer Agent.

This file assembles the tools the agent uses — both MCP-served and local —
in one place. The agent's `agent.py` just does `from .tools import tools`.

To add a tool:
- MCP-served:   add to the MCP toolset's `tool_filter=[…]` below.
- Local helper: define a function in this file (or import one) and append
                to `tools`.
"""

from __future__ import annotations

import os

from google.adk.tools.mcp_tool.mcp_session_manager import (
    StreamableHTTPConnectionParams,
)
from google.adk.tools.mcp_tool.mcp_toolset import McpToolset

_MCP_PORT = os.environ.get("MCP_SERVER_PORT", "8004")
_MCP_HOST = os.environ.get("MCP_SERVER_HOST", "localhost")
# Prefer MCP_SERVER_URL if set (e.g. the deployed Cloud Run URL written by
# `make deploy-mcp`); fall back to building http://host:port/mcp for local dev.
_MCP_URL = os.environ.get("MCP_SERVER_URL") or f"http://{_MCP_HOST}:{_MCP_PORT}/mcp"

mcp_tools = McpToolset(
    connection_params=StreamableHTTPConnectionParams(url=_MCP_URL),
    tool_filter=["explain_truthfulness_from_gcs"],
)

tools = [mcp_tools]
