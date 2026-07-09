"""`RemoteA2aAgent` wrapping the fine-tuned A2A server — for the orchestrator to consume without in-process imports."""

from __future__ import annotations
import os
from google.adk.agents.remote_a2a_agent import (
    AGENT_CARD_WELL_KNOWN_PATH,
    RemoteA2aAgent,
)

_PORT = os.environ.get("FINE_TUNED_A2A_PORT", "8002")
_HOST = os.environ.get("FINE_TUNED_A2A_HOST", "localhost")
_AGENT_CARD = (
    os.environ.get("FINE_TUNED_A2A_URL")
    or f"http://{_HOST}:{_PORT}{AGENT_CARD_WELL_KNOWN_PATH}"
)

fine_tuned_remote_agent = RemoteA2aAgent(
    name="fine_tuned_predictor",
    description=(
        "Two capabilities: (1) classifies political statements as truthful "
        "(True) or untruthful (False) using a fine-tuned Gemini model — send "
        "a batch of statement dicts, receive a list of booleans in the same "
        "order; if ground-truth labels are supplied alongside the statements, "
        "also returns headline classification metrics (accuracy, precision, "
        "recall, f1, confusion matrix); (2) reports on the underlying "
        "fine-tuning job — current state, whether the tuned endpoint is "
        "ready, and can refresh which endpoint future predictions use."
    ),
    agent_card=_AGENT_CARD,
    use_legacy=False,
)
