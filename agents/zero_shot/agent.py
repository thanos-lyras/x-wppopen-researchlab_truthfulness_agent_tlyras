"""Zero-shot predictor agent. Wraps the `predict_truthfulness_from_gcs` MCP tool on the zero-shot path."""

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
    model=os.environ.get("ZERO_SHOT_MODEL") or "gemini-2.5-flash",
    tools=tools,
)

root_agent = zero_shot_agent

# `to_a2a()` host/port/protocol go into the published agent card, NOT the uvicorn
# listen address. Cloud Run deploy injects *_PUBLIC_* so the card advertises the
# public HTTPS URL instead of `http://0.0.0.0:<port>`.
a2a_app = to_a2a(
    zero_shot_agent,
    host=os.environ.get("ZERO_SHOT_A2A_PUBLIC_HOST", "0.0.0.0"),
    port=int(os.environ.get(
        "ZERO_SHOT_A2A_PUBLIC_PORT",
        os.environ.get("ZERO_SHOT_A2A_PORT", "8001"),
    )),
    protocol=os.environ.get("ZERO_SHOT_A2A_PROTOCOL", "http"),
)
