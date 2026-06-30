"""Explainer Agent.

ADK 2.0 agent that produces natural-language explanations for truthfulness
verdicts on political statements.
Exposes `root_agent` so this folder can be launched standalone with
`adk web agents/explainer`, and `a2a_app` so it can be served over A2A via
`uvicorn agents.explainer.agent:a2a_app`.
"""

from __future__ import annotations

import os

from google.adk.a2a.utils.agent_to_a2a import to_a2a
from google.adk.agents import Agent

from .prompt import EXPLAINER_INSTRUCTION
from .tools import tools

explainer_agent = Agent(
    name="explainer",
    description=(
        "Explainer agent. Classifies political statements as True or False "
        "AND produces a short natural-language explanation for each verdict, "
        "in a single tool call. The underlying predictor (zero-shot by "
        "default, fine-tuned on request) drives the verdict; an independent "
        "free-form model articulates why. If the caller supplies ground-truth "
        "labels alongside the statements, also returns headline classification "
        "metrics (accuracy, precision, recall, f1, confusion matrix)."
    ),
    instruction=EXPLAINER_INSTRUCTION,
    model=os.environ.get("EXPLAINER_AGENT_MODEL", "gemini-2.5-flash"),
    tools=tools,
)

root_agent = explainer_agent

# `to_a2a()`'s host/port/protocol go into the published agent card — that's the
# URL remote callers (e.g. the orchestrator's RemoteA2aAgent) will POST to. It
# is NOT the uvicorn listen address (Cloud Run sets that via $PORT). For local
# dev the defaults work; in Cloud Run the deploy injects EXPLAINER_A2A_PUBLIC_HOST
# / EXPLAINER_A2A_PROTOCOL / EXPLAINER_A2A_PUBLIC_PORT so the card advertises the
# public HTTPS URL instead of `http://0.0.0.0:8003`.
a2a_app = to_a2a(
    explainer_agent,
    host=os.environ.get("EXPLAINER_A2A_PUBLIC_HOST", "0.0.0.0"),
    port=int(os.environ.get(
        "EXPLAINER_A2A_PUBLIC_PORT",
        os.environ.get("EXPLAINER_A2A_PORT", "8003"),
    )),
    protocol=os.environ.get("EXPLAINER_A2A_PROTOCOL", "http"),
)
