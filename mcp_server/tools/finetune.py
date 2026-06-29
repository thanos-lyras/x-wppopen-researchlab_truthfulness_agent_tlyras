"""`fine_tune_truthfulness` MCP tool — composes DatasetProcessor + GCSService + TuningManager."""

from __future__ import annotations

from google.adk.tools.function_tool import FunctionTool

from schemas.models import FineTuneRequest, FineTuneResponse, SplitCounts
from services.gcs_service import GCSService

from ..utils import config
from ..utils.dataset_processor import DatasetProcessor
from ..utils.tuning_manager import TuningManager


def fine_tune_truthfulness(req: FineTuneRequest) -> FineTuneResponse:
    """Fine-tune a Gemini model for binary truthfulness classification.

    See `schemas.models.FineTuneRequest` / `FineTuneResponse` for field-level docs.

    Behavior summary:
    - Prepares the dataset (6-way → binary label map + stratified 80/10/10 split).
    - Uploads train + val JSONL to GCS.
    - Submits a Vertex AI Gemini SFT job.
    - If `req.wait=True`, blocks until terminal state and fills `tuned_model`.
    """
    paths = DatasetProcessor().prepare(req.csv_path)

    gcs = GCSService()
    train_uri = gcs.upload(paths["train"], f"finetuning/{config.BASE_MODEL}/train.jsonl")
    val_uri   = gcs.upload(paths["val"],   f"finetuning/{config.BASE_MODEL}/val.jsonl")

    tuning = TuningManager()
    job = tuning.submit(train_uri, val_uri)

    split = SplitCounts(**{k: sum(1 for _ in open(p)) for k, p in paths.items()})
    state = str(job.state)
    tuned_model: str | None = None

    if req.wait:
        job = tuning.wait(job)
        state = str(job.state)
        if job.tuned_model and job.tuned_model.model:
            tuned_model = job.tuned_model.model

    return FineTuneResponse(
        split=split,
        train_gcs_uri=train_uri,
        val_gcs_uri=val_uri,
        job_name=job.name,
        state=state,
        tuned_model=tuned_model,
    )


fine_tune_truthfulness_tool = FunctionTool(fine_tune_truthfulness)
