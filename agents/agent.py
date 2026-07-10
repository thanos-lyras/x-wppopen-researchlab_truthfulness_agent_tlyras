"""Orchestrator agent. Root ADK entry. Delegates to sub-agents over A2A and exposes a `POST /invoke` REST route."""

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
    model=os.environ.get("ORCHESTRATOR_MODEL") or "gemini-2.5-flash",
    sub_agents=[fine_tuned_remote_agent, zero_shot_remote_agent, explainer_remote_agent],
)

root_agent = orchestrator_agent

# `to_a2a()` host/port/protocol go into the published agent card, NOT the uvicorn
# listen address. Cloud Run deploy injects *_PUBLIC_* so the card advertises the
# public HTTPS URL instead of `http://0.0.0.0:<port>`.
a2a_app = to_a2a(
    orchestrator_agent,
    host=os.environ.get("ORCHESTRATOR_A2A_PUBLIC_HOST", "0.0.0.0"),
    port=int(os.environ.get(
        "ORCHESTRATOR_A2A_PUBLIC_PORT",
        os.environ.get("ORCHESTRATOR_A2A_PORT", "8000"),
    )),
    protocol=os.environ.get("ORCHESTRATOR_A2A_PROTOCOL", "http"),
)


# POST /invoke: multipart (instruction + file). Uploads file to GCS, self-calls
# the A2A endpoint with the URI in the prompt so the orchestrator LLM routes to
# whichever sub-agent fits, then deletes the GCS object.
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
