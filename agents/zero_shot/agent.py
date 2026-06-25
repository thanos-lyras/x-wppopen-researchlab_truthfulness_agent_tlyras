"""Zero-shot Predictor Agent.

ADK 2.0 agent that wraps the zero-shot prediction tool from `tools.py`.
Exposes `root_agent` so this folder can be launched standalone with
`adk web agents/zero_shot`, and `a2a_app` so it can be served over A2A via
`uvicorn agents.zero_shot.agent:a2a_app`.
"""

from __future__ import annotations

import os

from google.adk.a2a.utils.agent_to_a2a import to_a2a
from google.adk.agents import Agent

from .prompt import ZERO_SHOT_INSTRUCTION
from .tools import tools

zero_shot_agent = Agent(
    name="zero_shot_predictor",
    description=(
        "Zero-shot LLM predictor. Classifies political statements as True or "
        "False using only the LLM's prior knowledge — no fine-tuning, no "
        "retrieval. Processes batches in a single tool call. If the caller "
        "supplies ground-truth labels alongside the statements, also returns "
        "headline classification metrics (accuracy, precision, recall, f1, "
        "confusion matrix) treating True as the positive class."
    ),
    instruction=ZERO_SHOT_INSTRUCTION,
    model=os.environ.get("ZERO_SHOT_AGENT_MODEL", "gemini-2.5-flash"),
    tools=tools,
)

root_agent = zero_shot_agent

a2a_app = to_a2a(
    zero_shot_agent,
    host="0.0.0.0",
    port=int(os.environ.get("ZERO_SHOT_A2A_PORT", "8001")),
)
