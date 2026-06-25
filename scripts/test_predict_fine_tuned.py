"""Smoke-test the unified `predict_truthfulness` MCP tool — fine-tuned path.

Connects to the running MCP server over Streamable HTTP, confirms the tool is
registered, then calls it twice with `use_fine_tuned=True`:
  1. without labels — exercises the predictions-only path
  2. with labels    — exercises the metrics-enabled path (accuracy, f1, etc.)

Prereq:  `make run-mcp` is running in another terminal.

Usage:
    make test-fine-tuned
    # or
    python -m scripts.test_predict_fine_tuned
"""

from __future__ import annotations

import asyncio
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
_GROUND_TRUTH = [True, False]


def _payload_text(result) -> str:
    """Pull the first TextContent block from an MCP CallToolResult."""
    for block in result.content:
        text = getattr(block, "text", None)
        if text is not None:
            return text
    return str(result.content)


async def main() -> None:
    resolved = os.environ.get("FINE_TUNED_MODEL") or f"(fallback) {config.BASE_MODEL}"
    print(f"▶ MCP endpoint:  {_MCP_URL}")
    print(f"▶ Resolved model: {resolved}\n")

    async with streamablehttp_client(_MCP_URL) as (read, write, _):
        async with ClientSession(read, write) as session:
            await session.initialize()

            tools = await session.list_tools()
            names = [t.name for t in tools.tools]
            print(f"▶ Tools registered: {names}")
            assert "predict_truthfulness" in names, (
                "predict_truthfulness not exposed by the MCP server"
            )

            # Path 1: predictions only — metrics should be None
            print("\n▶ Call without labels (use_fine_tuned=True):")
            result = await session.call_tool(
                "predict_truthfulness",
                arguments={"points": _SAMPLE_POINTS, "use_fine_tuned": True},
            )
            print(_payload_text(result))

            # Path 2: predictions + metrics — pass ground-truth labels
            print("\n▶ Call with labels (use_fine_tuned=True):")
            result = await session.call_tool(
                "predict_truthfulness",
                arguments={
                    "points": _SAMPLE_POINTS,
                    "use_fine_tuned": True,
                    "labels": _GROUND_TRUTH,
                },
            )
            print(_payload_text(result))


if __name__ == "__main__":
    asyncio.run(main())
