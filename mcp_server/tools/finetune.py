"""`fine_tune_truthfulness` MCP tool — composes DatasetService + GCSService + TuningService."""

from __future__ import annotations

from google.adk.tools.function_tool import FunctionTool

from ..utils import config
from ..utils.dataset_service import DatasetService
from ..utils.gcs_service import GCSService
from ..utils.tuning_service import TuningService


def fine_tune_truthfulness(
    csv_path: str | None = None,
    wait: bool = False,
) -> dict:
    """Fine-tune a Gemini model for binary truthfulness classification.

    Performs data preparation (6-way → binary label mapping + stratified 80/10/10
    split), uploads train+val JSONL to GCS, and submits a Vertex AI Gemini SFT job.

    Args:
        csv_path: Path to a CSV with the same columns as `data.csv`
            (including a `Label` column). If omitted, uses the project's default
            `data.csv` from `mcp_server/utils/config.py`.
        wait: If True, block until the SFT job reaches a terminal state and
            return the tuned-model resource name. If False (default), submit and
            return the job name immediately — the caller is responsible for polling.

    Returns:
        Dict with: `split` (row counts per split), `train_gcs_uri`, `val_gcs_uri`,
        `job_name` (Vertex tuning job resource name), `state`, `tuned_model`
        (resource name if `wait=True` and job succeeded; else None).
    """
    paths = DatasetService().prepare(csv_path)

    gcs = GCSService()
    train_uri = gcs.upload(paths["train"], f"finetuning/{config.BASE_MODEL}/train.jsonl")
    val_uri   = gcs.upload(paths["val"],   f"finetuning/{config.BASE_MODEL}/val.jsonl")

    tuning = TuningService()
    job = tuning.submit(train_uri, val_uri)

    result = {
        "split": {k: sum(1 for _ in open(p)) for k, p in paths.items()},
        "train_gcs_uri": train_uri,
        "val_gcs_uri":   val_uri,
        "job_name":      job.name,
        "state":         str(job.state),
        "tuned_model":   None,
    }

    if wait:
        job = tuning.wait(job)
        result["state"] = str(job.state)
        if job.tuned_model and job.tuned_model.model:
            result["tuned_model"] = job.tuned_model.model

    return result


fine_tune_truthfulness_tool = FunctionTool(fine_tune_truthfulness)
