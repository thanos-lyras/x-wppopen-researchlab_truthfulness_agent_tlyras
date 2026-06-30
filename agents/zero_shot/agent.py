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
    # `or` (not the dict default) so the fallback also kicks in when the env
    # var is set-but-empty — e.g. when `.env` has `ZERO_SHOT_MODEL=` or the
    # Cloud Run deploy passes `KEY=$VAR` with VAR unset (shell expands to "").
    model=os.environ.get("ZERO_SHOT_MODEL") or "gemini-2.5-flash",
    tools=tools,
)

root_agent = zero_shot_agent

# `to_a2a()`'s host/port/protocol go into the published agent card — that's the
# URL remote callers (e.g. the orchestrator's RemoteA2aAgent) will POST to. It
# is NOT the uvicorn listen address (Cloud Run sets that via $PORT). For local
# dev the defaults work; in Cloud Run the deploy injects ZERO_SHOT_A2A_PUBLIC_HOST
# / ZERO_SHOT_A2A_PROTOCOL / ZERO_SHOT_A2A_PUBLIC_PORT so the card advertises the
# public HTTPS URL instead of `http://0.0.0.0:8001`.
a2a_app = to_a2a(
    zero_shot_agent,
    host=os.environ.get("ZERO_SHOT_A2A_PUBLIC_HOST", "0.0.0.0"),
    port=int(os.environ.get(
        "ZERO_SHOT_A2A_PUBLIC_PORT",
        os.environ.get("ZERO_SHOT_A2A_PORT", "8001"),
    )),
    protocol=os.environ.get("ZERO_SHOT_A2A_PROTOCOL", "http"),
)
