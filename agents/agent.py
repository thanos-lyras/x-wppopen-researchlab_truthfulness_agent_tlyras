"""Orchestrator Agent.

Root ADK 2.0 agent. Entry point for verifying statements. Delegates to the
zero-shot predictor over A2A (via `RemoteA2aAgent`) — does NOT import the
sub-agent's Python in-process. Requires the zero_shot A2A server to be
running (`make run-a2a NAME=zero_shot`, or `make dev` to run the full stack).

Exposes `root_agent` (for `adk web agents`) and `a2a_app` (for
`uvicorn agents.agent:a2a_app` — see `make run-a2a NAME=orchestrator`).
"""

from __future__ import annotations

import os

from google.adk.a2a.utils.agent_to_a2a import to_a2a
from google.adk.agents import Agent

from agents.zero_shot.client import zero_shot_remote_agent

from .prompt import ORCHESTRATOR_INSTRUCTION


orchestrator_agent = Agent(
    name="truthfulness_orchestrator",
    description=(
        "Orchestrator for truthfulness classification. Delegates batches of "
        "statements to specialist predictor and explainer sub-agents over A2A "
        "and returns a consolidated verdict per statement."
    ),
    instruction=ORCHESTRATOR_INSTRUCTION,
    model=os.environ.get("ORCHESTRATOR_MODEL", "gemini-2.5-flash"),
    sub_agents=[zero_shot_remote_agent],
)

root_agent = orchestrator_agent

a2a_app = to_a2a(
    orchestrator_agent,
    host="0.0.0.0",
    port=int(os.environ.get("ORCHESTRATOR_A2A_PORT", "8000")),
)
