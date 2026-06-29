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
# In unified deployment (`make deploy-unified`), the unified app automatically
# sets EXPLAINER_A2A_URL to point to its loopback port. Prefer it when set;
# fall back to localhost for `make dev`.
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
