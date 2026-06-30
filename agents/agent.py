"""Orchestrator Agent.

Root ADK 2.0 agent. Entry point for verifying and explaining statements.
Delegates to the zero-shot predictor, fine-tuned predictor, and explainer
over A2A (via `RemoteA2aAgent`) — does NOT import the sub-agents' Python
in-process. Requires all three A2A servers to be running:
`make run-a2a NAME=zero_shot`, `make run-a2a NAME=fine_tuned`,
`make run-a2a NAME=explainer` (or just `make dev`).

Exposes `root_agent` (for `adk web agents`) and `a2a_app` (for
`uvicorn agents.agent:a2a_app` — see `make run-a2a NAME=orchestrator`).
"""

from __future__ import annotations

import os

from google.adk.a2a.utils.agent_to_a2a import to_a2a
from google.adk.agents import Agent

from agents.explainer.client import explainer_remote_agent
from agents.fine_tuned.client import fine_tuned_remote_agent
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
    sub_agents=[fine_tuned_remote_agent, zero_shot_remote_agent, explainer_remote_agent],
)

root_agent = orchestrator_agent

# `to_a2a()`'s host/port/protocol go into the published agent card — that's the
# URL remote callers will POST to. It is NOT the uvicorn listen address (Cloud
# Run sets that via $PORT). For local dev the defaults work; in Cloud Run the
# deploy injects ORCHESTRATOR_A2A_PUBLIC_HOST / ORCHESTRATOR_A2A_PROTOCOL /
# ORCHESTRATOR_A2A_PUBLIC_PORT so the card advertises the public HTTPS URL
# instead of `http://0.0.0.0:8000`.
a2a_app = to_a2a(
    orchestrator_agent,
    host=os.environ.get("ORCHESTRATOR_A2A_PUBLIC_HOST", "0.0.0.0"),
    port=int(os.environ.get(
        "ORCHESTRATOR_A2A_PUBLIC_PORT",
        os.environ.get("ORCHESTRATOR_A2A_PORT", "8000"),
    )),
    protocol=os.environ.get("ORCHESTRATOR_A2A_PROTOCOL", "http"),
)
