"""Fine-tuned Predictor Agent.

ADK 2.0 agent that wraps the truthfulness prediction tool, backed by a
fine-tuned Gemini model (resource set via `FINE_TUNED_MODEL` in `.env`).
Exposes `root_agent` so this folder can be launched standalone with
`adk web agents/fine_tuned`, and `a2a_app` so it can be served over A2A via
`uvicorn agents.fine_tuned.agent:a2a_app`.
"""

from __future__ import annotations

import os

from google.adk.a2a.utils.agent_to_a2a import to_a2a
from google.adk.agents import Agent

from .prompt import FINE_TUNED_INSTRUCTION
from .tools import tools

fine_tuned_agent = Agent(
    name="fine_tuned_predictor",
    description=(
        "Fine-tuned LLM predictor. Two capabilities: (1) classifies political "
        "statements as True or False using a Gemini model fine-tuned on the "
        "project's training split, processing batches in a single tool call — "
        "and if the caller supplies ground-truth labels alongside the "
        "statements, also returns headline classification metrics (accuracy, "
        "precision, recall, f1, confusion matrix); (2) reports on the "
        "underlying fine-tuning job — current state, whether the tuned "
        "endpoint is ready, and can refresh which endpoint future predictions "
        "use."
    ),
    instruction=FINE_TUNED_INSTRUCTION,
    model=os.environ.get("FINE_TUNED_AGENT_MODEL", "gemini-2.5-flash"),
    tools=tools,
)

root_agent = fine_tuned_agent

a2a_app = to_a2a(
    fine_tuned_agent,
    host="0.0.0.0",
    port=int(os.environ.get("FINE_TUNED_A2A_PORT", "8002")),
)
