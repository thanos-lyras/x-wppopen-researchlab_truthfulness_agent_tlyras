"""Tool manifest for the Zero-shot Predictor Agent.

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

_MCP_URL = os.environ.get("MCP_SERVER_URL") or "http://localhost:8004/mcp/"

mcp_tools = McpToolset(
    connection_params=StreamableHTTPConnectionParams(url=_MCP_URL),
    tool_filter=["predict_truthfulness"],
)

tools = [mcp_tools]
