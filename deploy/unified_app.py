"""Unified ASGI Application for deploying MCP + 4 Agents in a single Cloud Run service."""

import contextlib
import os
from collections.abc import AsyncIterator

# Set self-configuring local loopback URLs before importing any clients.
# This ensures that internal A2A communication dynamically targets the correct port
# assigned by Cloud Run (defaulting to 8080).
PORT = os.environ.get("PORT", "8080")
os.environ["ZERO_SHOT_A2A_URL"] = f"http://127.0.0.1:{PORT}/zero_shot/.well-known/agent-card.json"
os.environ["FINE_TUNED_A2A_URL"] = f"http://127.0.0.1:{PORT}/fine_tuned/.well-known/agent-card.json"
os.environ["EXPLAINER_A2A_URL"] = f"http://127.0.0.1:{PORT}/explainer/.well-known/agent-card.json"
os.environ["MCP_SERVER_URL"] = f"http://127.0.0.1:{PORT}/mcp/"

from starlette.applications import Starlette
from starlette.routing import Mount

# 1. Initialize MCP server and its low-level session manager
from mcp_server.server import TruthfulnessMcpServer
from mcp_server.tools.check_finetune_status import check_finetune_status_tool
from mcp_server.tools.explain import explain_truthfulness_tool
from mcp_server.tools.finetune import fine_tune_truthfulness_tool
from mcp_server.tools.predict import predict_truthfulness_tool

mcp_server_instance = TruthfulnessMcpServer(tools=[
    predict_truthfulness_tool,
    explain_truthfulness_tool,
    fine_tune_truthfulness_tool,
    check_finetune_status_tool,
])

from mcp.server.streamable_http_manager import StreamableHTTPSessionManager
mcp_session = StreamableHTTPSessionManager(app=mcp_server_instance._mcp, stateless=True)

# 2. Import Agent A2A applications (these will now read the environment vars set above)
from agents.zero_shot.agent import a2a_app as zero_shot_app
from agents.fine_tuned.agent import a2a_app as fine_tuned_app
from agents.explainer.agent import a2a_app as explainer_app
from agents.agent import a2a_app as orchestrator_app


# 3. Handle unified lifespan manager
@contextlib.asynccontextmanager
async def unified_lifespan(app: Starlette) -> AsyncIterator[None]:
    # Start the MCP session background loop
    async with mcp_session.run():
        yield


# 4. Expose the unified application
app = Starlette(
    routes=[
        Mount("/mcp", app=mcp_session.handle_request),
        Mount("/zero_shot", app=zero_shot_app),
        Mount("/fine_tuned", app=fine_tuned_app),
        Mount("/explainer", app=explainer_app),
        Mount("/", app=orchestrator_app),
    ],
    lifespan=unified_lifespan,
)
