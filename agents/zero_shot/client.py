"""`RemoteA2aAgent` wrapping the zero-shot A2A server — for the orchestrator to consume without in-process imports."""

from __future__ import annotations
import os
import httpx
from google.adk.agents.remote_a2a_agent import (
    AGENT_CARD_WELL_KNOWN_PATH,
    RemoteA2aAgent,
)
from services.gcp_auth import IdTokenAuth, is_cloud_run_url

_PORT = os.environ.get("ZERO_SHOT_A2A_PORT", "8001")
_HOST = os.environ.get("ZERO_SHOT_A2A_HOST", "localhost")
_AGENT_CARD = (
    os.environ.get("ZERO_SHOT_A2A_URL")
    or f"http://{_HOST}:{_PORT}{AGENT_CARD_WELL_KNOWN_PATH}"
)

# Cloud Run rejects requests without an ID token (per-hop IAM). Local dev uses
# plain HTTP against localhost — skip the auth flow so we don't fail to mint.
_base_url = _AGENT_CARD.rsplit("/.well-known", 1)[0]
# timeout=600 matches RemoteA2aAgent's default — a custom httpx client would
# otherwise inherit httpx's 5s default, which trips sub-agent cold-starts.
_httpx_client = (
    httpx.AsyncClient(auth=IdTokenAuth(_base_url), timeout=600.0)
    if is_cloud_run_url(_base_url) else None
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
    httpx_client=_httpx_client,
    use_legacy=False,
)
