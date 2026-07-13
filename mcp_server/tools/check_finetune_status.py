"""`check_finetune_status` MCP tool — poll the last SFT job; on success, self-heal FINE_TUNED_MODEL."""

from __future__ import annotations
import os
from dotenv import set_key
from google.adk.tools.function_tool import FunctionTool
from schemas.models import JobStatusResponse, NoJobResponse
from services.vertex_client import client


def check_finetune_status() -> NoJobResponse | JobStatusResponse:
    """Poll LAST_TUNING_JOB; on SUCCEEDED, write the deployed endpoint to FINE_TUNED_MODEL (.env + os.environ)."""
    # Read live from os.environ (not config.LAST_TUNING_JOB which freezes at import)
    # so a job submitted via fine_tune_truthfulness in the same process is visible.
    job_name = os.environ.get("LAST_TUNING_JOB")
    if not job_name:
        return NoJobResponse(
            status="no_job",
            message="no tuning job recorded — submit one first via fine_tune_truthfulness",
        )

    job = client.tunings.get(name=job_name)
    state = job.state.name

    if state == "JOB_STATE_SUCCEEDED" and job.tuned_model and job.tuned_model.endpoint:
        endpoint = job.tuned_model.endpoint
        # Compare against live os.environ, not config.FINE_TUNED_MODEL (frozen at import).
        if endpoint != os.environ.get("FINE_TUNED_MODEL"):
            set_key(".env", "FINE_TUNED_MODEL", endpoint, quote_mode="never")
            # Push into this process's env too so predict picks up the endpoint without restart.
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
        job_name=job_name,
        state=state,
        endpoint=endpoint,
        endpoint_updated=endpoint_updated,
        message=message,
    )


check_finetune_status_tool = FunctionTool(check_finetune_status)
