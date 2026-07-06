"""Orchestrator Agent.

Root ADK 2.0 agent. Entry point for verifying and explaining statements.
Delegates to the zero-shot predictor, fine-tuned predictor, and explainer
over A2A (via `RemoteA2aAgent`) — does NOT import the sub-agents' Python
in-process. Requires all three A2A servers to be running:
`make run-a2a NAME=zero_shot`, `make run-a2a NAME=fine_tuned`,
`make run-a2a NAME=explainer` (or just `make dev`).

Exposes:
- `root_agent` — for `adk web agents`.
- `a2a_app` — Starlette app from `to_a2a()`. Serves A2A JSON-RPC at `/`,
  the agent card at `/.well-known/agent-card.json`, plus one REST route:
    `POST /invoke` — multipart/form-data with two fields:
        instruction: free-form text telling the orchestrator what to do
                     ("predict on this", "explain these", "fine-tune…")
        file:        the uploaded file (JSON batch, CSV, …)
    The handler uploads the file to `gs://$GCS_BUCKET/uploads/<uuid>.<ext>`,
    asks the orchestrator's LLM to process it (the LLM reads the instruction
    and routes to the right sub-agent), and deletes the GCS object after.
  Try it with curl:
    curl -X POST http://localhost:8000/invoke \\
      -F "instruction=please classify these statements" \\
      -F "file=@data/sample_1.json"
"""

from __future__ import annotations

import os
import uuid

import httpx
from google.adk.a2a.utils.agent_to_a2a import to_a2a
from google.adk.agents import Agent
from starlette.responses import JSONResponse

from agents.explainer.client import explainer_remote_agent
from agents.fine_tuned.client import fine_tuned_remote_agent
from agents.zero_shot.client import zero_shot_remote_agent
from services.gcs_service import GCSService

from .prompt import ORCHESTRATOR_INSTRUCTION


orchestrator_agent = Agent(
    name="truthfulness_orchestrator",
    description=(
        "Orchestrator for truthfulness classification. Delegates batches of "
        "statements to specialist predictor and explainer sub-agents over A2A "
        "and returns a consolidated verdict per statement."
    ),
    instruction=ORCHESTRATOR_INSTRUCTION,
    # `or` (not the dict default) so the fallback also kicks in when the env
    # var is set-but-empty — e.g. when `.env` has `ORCHESTRATOR_MODEL=` or the
    # Cloud Run deploy passes `KEY=$VAR` with VAR unset (shell expands to "").
    model=os.environ.get("ORCHESTRATOR_MODEL") or "gemini-2.5-flash",
    sub_agents=[fine_tuned_remote_agent, zero_shot_remote_agent, explainer_remote_agent],
)

root_agent = orchestrator_agent

# `to_a2a()`'s host/port/protocol go into the published agent card — that's the
# URL remote callers will POST to. It is NOT the uvicorn listen address (Cloud
# Run sets that via $PORT). For local dev the defaults work; in Cloud Run the
# deploy injects ORCHESTRATOR_A2A_PUBLIC_HOST / ORCHESTRATOR_A2A_PROTOCOL /
# ORCHESTRATOR_A2A_PUBLIC_PORT so the card advertises the public HTTPS URL
# instead of `http://0.0.0.0:8000`.
a2a_app = to_a2a(
    orchestrator_agent,
    host=os.environ.get("ORCHESTRATOR_A2A_PUBLIC_HOST", "0.0.0.0"),
    port=int(os.environ.get(
        "ORCHESTRATOR_A2A_PUBLIC_PORT",
        os.environ.get("ORCHESTRATOR_A2A_PORT", "8000"),
    )),
    protocol=os.environ.get("ORCHESTRATOR_A2A_PROTOCOL", "http"),
)


# ── POST /invoke ────────────────────────────────────────────────────────────
# Multipart: instruction (str) + file (uploaded bytes). Upload the file to
# GCS, paste the URI into a natural-language A2A message, self-call our own
# A2A endpoint. The orchestrator LLM reads the instruction + URI and routes
# to whichever sub-agent fits — no hardcoded task field, fully agentic.

async def _invoke(request):
    try:
        form = await request.form()
        instruction = (form.get("instruction") or "").strip()
        upload = form.get("file")
        if not instruction or upload is None:
            return JSONResponse(
                {"error": "multipart form must include both 'instruction' and 'file' fields"},
                status_code=400,
            )
        file_bytes = await upload.read()
        suffix = ("." + upload.filename.rsplit(".", 1)[-1]) if upload.filename and "." in upload.filename else ""
    except Exception as e:
        return JSONResponse({"error": "could not parse multipart body", "detail": str(e)}, status_code=400)

    gcs = GCSService()
    uri = gcs.upload_bytes(file_bytes, f"uploads/{uuid.uuid4()}{suffix}")
    try:
        port = os.environ.get("PORT") or os.environ.get("ORCHESTRATOR_A2A_PORT", "8000")
        a2a_body = {
            "jsonrpc": "2.0", "id": str(uuid.uuid4()),
            "method": "message/send",
            "params": {"message": {
                "role": "user",
                "parts": [{"kind": "text", "text": f"{instruction}\n\nThe uploaded file is available at the GCS URI: {uri}"}],
                "messageId": str(uuid.uuid4()),
            }},
        }
        async with httpx.AsyncClient(timeout=180.0) as client:
            resp = await client.post(f"http://localhost:{port}/", json=a2a_body)
        rj = resp.json()
        texts = [
            part["text"]
            for a in rj.get("result", {}).get("artifacts", []) or []
            for part in a.get("parts", [])
            if part.get("kind") == "text"
        ]
        return JSONResponse({"answer": "\n".join(texts), "raw": rj})
    finally:
        try:
            gcs.delete(uri)
        except Exception as e:
            print(f"warning: failed to delete {uri}: {e}")


a2a_app.add_route("/invoke", _invoke, methods=["POST"])
