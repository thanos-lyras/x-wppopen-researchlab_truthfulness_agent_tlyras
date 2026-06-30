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
    # Two distinct env vars here:
    #   FINE_TUNED_MODEL       — the *prediction-endpoint* path (Vertex AI tuned
    #                            endpoint). Read by the MCP `predict_truthfulness`
    #                            tool, NOT by this agent.
    #   FINE_TUNED_AGENT_MODEL — the LLM this wrapping ADK agent uses for tool
    #                            routing / response formatting. Defaults to flash;
    #                            override only if you want a different model at
    #                            the agent layer than at the prediction layer.
    # `or` (not the dict default) so the fallback handles set-but-empty too.
    model=os.environ.get("FINE_TUNED_AGENT_MODEL") or "gemini-2.5-flash",
    tools=tools,
)

root_agent = fine_tuned_agent

# `to_a2a()`'s host/port/protocol go into the published agent card — that's the
# URL remote callers (e.g. the orchestrator's RemoteA2aAgent) will POST to. It
# is NOT the uvicorn listen address (Cloud Run sets that via $PORT). For local
# dev the defaults work; in Cloud Run the deploy injects FINE_TUNED_A2A_PUBLIC_HOST
# / FINE_TUNED_A2A_PROTOCOL / FINE_TUNED_A2A_PUBLIC_PORT so the card advertises
# the public HTTPS URL instead of `http://0.0.0.0:8002`.
a2a_app = to_a2a(
    fine_tuned_agent,
    host=os.environ.get("FINE_TUNED_A2A_PUBLIC_HOST", "0.0.0.0"),
    port=int(os.environ.get(
        "FINE_TUNED_A2A_PUBLIC_PORT",
        os.environ.get("FINE_TUNED_A2A_PORT", "8002"),
    )),
    protocol=os.environ.get("FINE_TUNED_A2A_PROTOCOL", "http"),
)
