"""Tool manifest — the agent's `agent.py` just does `from .tools import tools`."""

from __future__ import annotations
import os
from google.adk.tools.mcp_tool.mcp_session_manager import (
    StreamableHTTPConnectionParams,
)
from google.adk.tools.mcp_tool.mcp_toolset import McpToolset
from services.gcp_auth import mint_id_token, is_cloud_run_url

_MCP_PORT = os.environ.get("MCP_SERVER_PORT", "8004")
_MCP_HOST = os.environ.get("MCP_SERVER_HOST", "localhost")
_MCP_URL = os.environ.get("MCP_SERVER_URL") or f"http://{_MCP_HOST}:{_MCP_PORT}/mcp"

# Audience for the ID token = MCP's base URL (no /mcp/ suffix).
_MCP_BASE = _MCP_URL.rsplit("/mcp", 1)[0]


def _auth_headers(_ctx):
    if not is_cloud_run_url(_MCP_BASE):
        return {}
    return {"Authorization": f"Bearer {mint_id_token(_MCP_BASE)}"}


mcp_tools = McpToolset(
    connection_params=StreamableHTTPConnectionParams(url=_MCP_URL),
    tool_filter=["predict_truthfulness_from_gcs", "check_finetune_status"],
    header_provider=_auth_headers,
)

tools = [mcp_tools]
