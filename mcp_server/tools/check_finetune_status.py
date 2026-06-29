"""`check_finetune_status` MCP tool — poll the last SFT job and auto-update FINE_TUNED_MODEL.

Reads `LAST_TUNING_JOB` (written by `TuningManager.submit()` into `.env`), queries
Vertex for the job's current state, and — if SUCCEEDED — writes the deployed
endpoint into `FINE_TUNED_MODEL` (both to `.env` for next boot and to the running
process's `os.environ` so the predict tool picks it up on the next call). Idempotent:
re-running after the endpoint is already set is a no-op.

Intended workflow:
    1. user calls `fine_tune_truthfulness(wait=false)`  → submits job, .env gets LAST_TUNING_JOB
    2. (~30-90 min pass; user may close their agent)
    3. user calls `check_finetune_status`               → updates FINE_TUNED_MODEL if ready
    4. user calls `predict_truthfulness(..., use_fine_tuned=True)` → immediately hits the tuned endpoint
"""

from __future__ import annotations

import os

from dotenv import set_key
from google.adk.tools.function_tool import FunctionTool

from schemas.models import JobStatusResponse, NoJobResponse
from services.vertex_client import client

from ..utils import config


def check_finetune_status() -> NoJobResponse | JobStatusResponse:
    """Check the latest submitted SFT job and self-heal FINE_TUNED_MODEL on success.

    Reads `LAST_TUNING_JOB` from the environment (populated by `fine_tune_truthfulness`).
    Queries Vertex for the job's current state. If the job has succeeded and produced
    a deployed endpoint, writes that endpoint to `FINE_TUNED_MODEL` in `.env` — unless
    `.env` already has the same value, in which case nothing is written.

    See `schemas.models.NoJobResponse` / `JobStatusResponse` for field-level docs.
    """
    if not config.LAST_TUNING_JOB:
        return NoJobResponse(
            status="no_job",
            message="no tuning job recorded — submit one first via fine_tune_truthfulness",
        )

    job = client.tunings.get(name=config.LAST_TUNING_JOB)
    state = job.state.name

    if state == "JOB_STATE_SUCCEEDED" and job.tuned_model and job.tuned_model.endpoint:
        endpoint = job.tuned_model.endpoint
        # Compare against os.environ (the live value in this process), not
        # config.FINE_TUNED_MODEL which freezes at module import.
        if endpoint != os.environ.get("FINE_TUNED_MODEL"):
            # Persist to .env for the next process boot...
            set_key(".env", "FINE_TUNED_MODEL", endpoint, quote_mode="never")
            # ...AND push into this process's env so predict_fine_tuned's
            # _resolve_model() picks up the new endpoint on the very next call,
            # with no MCP server restart required.
            os.environ["FINE_TUNED_MODEL"] = endpoint
            message = (
                f"updated FINE_TUNED_MODEL to {endpoint}. "
                "Next predict_truthfulness(..., use_fine_tuned=True) call will use the tuned endpoint."
            )
            endpoint_updated = True
        else:
            message = "endpoint already up-to-date"
            endpoint_updated = False
    elif state in ("JOB_STATE_FAILED", "JOB_STATE_CANCELLED"):
        endpoint = None
        message = f"job ended in {state} — no endpoint produced"
        endpoint_updated = False
    else:
        endpoint = None
        message = f"job still running (state={state}) — try again later"
        endpoint_updated = False

    return JobStatusResponse(
        job_name=config.LAST_TUNING_JOB,
        state=state,
        endpoint=endpoint,
        endpoint_updated=endpoint_updated,
        message=message,
    )


check_finetune_status_tool = FunctionTool(check_finetune_status)
