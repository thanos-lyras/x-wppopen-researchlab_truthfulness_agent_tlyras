"""Remote client for the explainer agent.

Wraps the running A2A server (`make run-a2a NAME=explainer`) as a
`RemoteA2aAgent` so the orchestrator (or any other agent) can delegate to
it over A2A — without importing explainer's Python code in-process.

The port comes from `EXPLAINER_A2A_PORT` in `.env`, the same var the
server-side `a2a_app` reads, so the card URL and bind port always match.
"""

from __future__ import annotations

import os

from google.adk.agents.remote_a2a_agent import (
    AGENT_CARD_WELL_KNOWN_PATH,
    RemoteA2aAgent,
)

_PORT = os.environ.get("EXPLAINER_A2A_PORT", "8003")
_HOST = os.environ.get("EXPLAINER_A2A_HOST", "localhost")

explainer_remote_agent = RemoteA2aAgent(
    name="explainer",
    description=(
        "Produces natural-language explanations for True/False verdicts on "
        "political statements. Send a batch of statement dicts; receive a "
        "list of explanations in the same order."
    ),
    agent_card=f"http://{_HOST}:{_PORT}{AGENT_CARD_WELL_KNOWN_PATH}",
    use_legacy=False,
)
