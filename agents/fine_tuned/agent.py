"""Fine-tuned predictor agent. Wraps `predict_truthfulness_from_gcs` (tuned endpoint) + `check_finetune_status`."""

from __future__ import annotations
import os
from google.adk.a2a.utils.agent_to_a2a import to_a2a
from google.adk.agents import Agent
from .prompt import FINE_TUNED_INSTRUCTION
from .tools import tools

fine_tuned_agent = Agent(
    name="fine_tuned_predictor",
    description=(
        "Fine-tuned LLM predictor. Three capabilities: (1) classifies political "
        "statements as True or False using a Gemini model fine-tuned on the "
        "project's training split, processing batches in a single tool call — "
        "and if the caller supplies ground-truth labels alongside the "
        "statements, also returns headline classification metrics (accuracy, "
        "precision, recall, f1, confusion matrix); (2) submits a new Vertex AI "
        "SFT job on an uploaded CSV dataset (returns immediately with the job "
        "name; training runs 30-90 min server-side); (3) reports on the "
        "underlying fine-tuning job — current state, whether the tuned "
        "endpoint is ready, and can refresh which endpoint future predictions "
        "use."
    ),
    instruction=FINE_TUNED_INSTRUCTION,
    # Two distinct env vars: FINE_TUNED_MODEL is the Vertex tuned-endpoint path
    # (read by the MCP predict tool); FINE_TUNED_AGENT_MODEL is the LLM this
    # wrapping agent uses for routing/formatting.
    model=os.environ.get("FINE_TUNED_AGENT_MODEL") or "gemini-2.5-flash",
    tools=tools,
)

root_agent = fine_tuned_agent

# `to_a2a()` host/port/protocol go into the published agent card, NOT the uvicorn
# listen address. Cloud Run deploy injects *_PUBLIC_* so the card advertises the
# public HTTPS URL instead of `http://0.0.0.0:<port>`.
a2a_app = to_a2a(
    fine_tuned_agent,
    host=os.environ.get("FINE_TUNED_A2A_PUBLIC_HOST", "0.0.0.0"),
    port=int(os.environ.get(
        "FINE_TUNED_A2A_PUBLIC_PORT",
        os.environ.get("FINE_TUNED_A2A_PORT", "8002"),
    )),
    protocol=os.environ.get("FINE_TUNED_A2A_PROTOCOL", "http"),
)
