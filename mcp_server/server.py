"""Streamable-HTTP MCP server: class + composed `app` for uvicorn."""

import contextlib
from collections.abc import AsyncIterator, Iterable

from google.adk.tools.function_tool import FunctionTool
from google.adk.tools.mcp_tool.conversion_utils import adk_to_mcp_tool_type
from mcp import types as mcp_types
from mcp.server.lowlevel import Server
from mcp.server.streamable_http_manager import StreamableHTTPSessionManager
from starlette.applications import Starlette
from starlette.routing import Mount

from .tools.finetune import fine_tune_truthfulness_tool
from .tools.predict import predict_truthfulness_tool
from .tools.predict_fine_tuned import predict_fine_tuned_truthfulness_tool


class TruthfulnessMcpServer:
    def __init__(self, tools: Iterable[FunctionTool], name: str = "truthfulness-mcp"):
        self._mcp = Server(name)
        self._tools = {t.name: t for t in tools}

        @self._mcp.list_tools()
        async def _list():
            return [adk_to_mcp_tool_type(t) for t in self._tools.values()]

        @self._mcp.call_tool()
        async def _call(name: str, arguments: dict):
            result = await self._tools[name].run_async(args=arguments, tool_context=None)
            return [mcp_types.TextContent(type="text", text=str(result))]

    def build_app(self) -> Starlette:
        session = StreamableHTTPSessionManager(app=self._mcp, stateless=True)

        @contextlib.asynccontextmanager
        async def lifespan(_: Starlette) -> AsyncIterator[None]:
            async with session.run():
                yield

        return Starlette(
            routes=[Mount("/mcp", app=session.handle_request)],
            lifespan=lifespan,
        )


# Compose tools here. To add a new tool: import it above and append to the list.
app = TruthfulnessMcpServer(tools=[
    predict_truthfulness_tool,
    predict_fine_tuned_truthfulness_tool,
    fine_tune_truthfulness_tool,
]).build_app()
