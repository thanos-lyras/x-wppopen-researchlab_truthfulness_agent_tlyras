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

fine_tuned_remote_agent = RemoteA2aAgent(
    name="fine_tuned_predictor",
    description=(
        "Classifies political statements as truthful (True) or untruthful "
        "(False) using a fine-tuned Gemini model. Send a batch of statement "
        "dicts; receive a list of booleans in the same order."
    ),
    agent_card=f"http://{_HOST}:{_PORT}{AGENT_CARD_WELL_KNOWN_PATH}",
    use_legacy=False,
)
