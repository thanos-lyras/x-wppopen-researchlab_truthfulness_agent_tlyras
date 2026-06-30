"""Remote client for the fine-tuned predictor agent.

Wraps the running A2A server (`make run-a2a NAME=fine_tuned`) as a
`RemoteA2aAgent` so the orchestrator (or any other agent) can delegate to
it over A2A — without importing fine_tuned's Python code in-process.

The port comes from `FINE_TUNED_A2A_PORT` in `.env`, the same var the
server-side `a2a_app` reads, so the card URL and bind port always match.
"""

from __future__ import annotations

import os

from google.adk.agents.remote_a2a_agent import (
    AGENT_CARD_WELL_KNOWN_PATH,
    RemoteA2aAgent,
)

_PORT = os.environ.get("FINE_TUNED_A2A_PORT", "8002")
_HOST = os.environ.get("FINE_TUNED_A2A_HOST", "localhost")
# Prefer FINE_TUNED_A2A_URL if set (e.g. the deployed Cloud Run agent-card URL
# written by `make deploy-fine-tuned`); fall back to localhost for local dev.
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
