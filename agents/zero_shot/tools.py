"""Tool manifest — the agent's `agent.py` just does `from .tools import tools`."""

from __future__ import annotations
import os
from google.adk.tools.mcp_tool.mcp_session_manager import (
    StreamableHTTPConnectionParams,
)
from google.adk.tools.mcp_tool.mcp_toolset import McpToolset

_MCP_PORT = os.environ.get("MCP_SERVER_PORT", "8004")
_MCP_HOST = os.environ.get("MCP_SERVER_HOST", "localhost")
_MCP_URL = os.environ.get("MCP_SERVER_URL") or f"http://{_MCP_HOST}:{_MCP_PORT}/mcp"

mcp_tools = McpToolset(
    connection_params=StreamableHTTPConnectionParams(url=_MCP_URL),
    tool_filter=["predict_truthfulness_from_gcs"],
)

tools = [mcp_tools]
