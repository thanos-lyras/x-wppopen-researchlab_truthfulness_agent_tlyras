"""Smoke-test the `predict_fine_tuned_truthfulness` MCP tool end-to-end.

Connects to the running MCP server over Streamable HTTP, lists tools to confirm
the fine-tuned predictor is registered, then calls it with a small batch and
prints the resolved model + predictions.

Prereq:  `make run-mcp` is running in another terminal.

Usage:
    make test-fine-tuned
    # or
    python -m scripts.test_predict_fine_tuned
"""

from __future__ import annotations

import asyncio
import json
import os

from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client

from mcp_server.utils import config

_MCP_PORT = os.environ.get("MCP_SERVER_PORT", "8004")
_MCP_HOST = os.environ.get("MCP_SERVER_HOST", "localhost")
_MCP_URL = f"http://{_MCP_HOST}:{_MCP_PORT}/mcp"

_SAMPLE_POINTS = [
    {"statement": "The Earth orbits the Sun."},
    {"statement": "The Great Wall of China is visible from space with the naked eye."},
]


async def main() -> None:
    resolved = config.FINE_TUNED_MODEL or f"(fallback) {config.BASE_MODEL}"
    print(f"▶ MCP endpoint:  {_MCP_URL}")
    print(f"▶ Resolved model: {resolved}\n")

    async with streamablehttp_client(_MCP_URL) as (read, write, _):
        async with ClientSession(read, write) as session:
            await session.initialize()

            tools = await session.list_tools()
            names = [t.name for t in tools.tools]
            print(f"▶ Tools registered: {names}")
            assert "predict_fine_tuned_truthfulness" in names, (
                "predict_fine_tuned_truthfulness not exposed by the MCP server"
            )

            result = await session.call_tool(
                "predict_fine_tuned_truthfulness",
                arguments={"points": _SAMPLE_POINTS},
            )

            print("\n▶ Raw tool response:")
            for block in result.content:
                text = getattr(block, "text", str(block))
                try:
                    print(json.dumps(json.loads(text), indent=2))
                except (ValueError, TypeError):
                    print(text)


if __name__ == "__main__":
    asyncio.run(main())
