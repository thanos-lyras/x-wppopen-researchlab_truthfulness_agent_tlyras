"""`RemoteA2aAgent` wrapping the zero-shot A2A server — for the orchestrator to consume without in-process imports."""

from __future__ import annotations
import os
from google.adk.agents.remote_a2a_agent import (
    AGENT_CARD_WELL_KNOWN_PATH,
    RemoteA2aAgent,
)

_PORT = os.environ.get("ZERO_SHOT_A2A_PORT", "8001")
_HOST = os.environ.get("ZERO_SHOT_A2A_HOST", "localhost")
_AGENT_CARD = (
    os.environ.get("ZERO_SHOT_A2A_URL")
    or f"http://{_HOST}:{_PORT}{AGENT_CARD_WELL_KNOWN_PATH}"
)

zero_shot_remote_agent = RemoteA2aAgent(
    name="zero_shot_predictor",
    description=(
        "Classifies political statements as truthful (True) or untruthful "
        "(False) using a zero-shot LLM. Send a batch of statement dicts; "
        "receive a list of booleans in the same order. If ground-truth labels "
        "are supplied alongside the statements, also returns headline "
        "classification metrics (accuracy, precision, recall, f1, confusion "
        "matrix)."
    ),
    agent_card=_AGENT_CARD,
    use_legacy=False,
)
