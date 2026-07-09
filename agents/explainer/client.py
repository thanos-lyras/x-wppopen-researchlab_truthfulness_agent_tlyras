"""`RemoteA2aAgent` wrapping the explainer A2A server — for the orchestrator to consume without in-process imports."""

from __future__ import annotations
import os
from google.adk.agents.remote_a2a_agent import (
    AGENT_CARD_WELL_KNOWN_PATH,
    RemoteA2aAgent,
)

_PORT = os.environ.get("EXPLAINER_A2A_PORT", "8003")
_HOST = os.environ.get("EXPLAINER_A2A_HOST", "localhost")
_AGENT_CARD = (
    os.environ.get("EXPLAINER_A2A_URL")
    or f"http://{_HOST}:{_PORT}{AGENT_CARD_WELL_KNOWN_PATH}"
)

explainer_remote_agent = RemoteA2aAgent(
    name="explainer",
    description=(
        "Classifies political statements as True or False AND produces a short "
        "natural-language explanation for each verdict, in a single tool call. "
        "The underlying predictor (zero-shot by default, fine-tuned on request) "
        "drives the verdict; an independent free-form model articulates why. "
        "If ground-truth labels are supplied alongside the statements, also "
        "returns headline classification metrics (accuracy, precision, recall, "
        "f1, confusion matrix)."
    ),
    agent_card=_AGENT_CARD,
    use_legacy=False,
)
