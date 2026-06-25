"""Remote client for the zero-shot predictor agent.

Wraps the running A2A server (`make run-a2a NAME=zero_shot`) as a
`RemoteA2aAgent` so the orchestrator (or any other agent) can delegate to
it over A2A — without importing zero_shot's Python code in-process.

The port comes from `ZERO_SHOT_A2A_PORT` in `.env`, the same var the
server-side `a2a_app` reads, so the card URL and bind port always match.
"""

from __future__ import annotations

import os

from google.adk.agents.remote_a2a_agent import (
    AGENT_CARD_WELL_KNOWN_PATH,
    RemoteA2aAgent,
)

_PORT = os.environ.get("ZERO_SHOT_A2A_PORT", "8001")
_HOST = os.environ.get("ZERO_SHOT_A2A_HOST", "localhost")

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
    agent_card=f"http://{_HOST}:{_PORT}{AGENT_CARD_WELL_KNOWN_PATH}",
    use_legacy=False,
)
