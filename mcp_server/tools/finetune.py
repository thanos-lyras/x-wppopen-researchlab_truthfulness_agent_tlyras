"""`fine_tune_truthfulness` MCP tool — composes DatasetProcessor + GCSService + TuningManager."""

from __future__ import annotations
from google.adk.tools.function_tool import FunctionTool
from schemas.models import FineTuneRequest, FineTuneResponse, SplitCounts
from services.gcs_service import GCSService
from ..utils import config
from ..utils.dataset_processor import DatasetProcessor
from ..utils.tuning_manager import TuningManager


def fine_tune_truthfulness(req: FineTuneRequest) -> FineTuneResponse:
    """Prepare dataset → upload to GCS → submit Vertex SFT (blocks until done if `req.wait`).

    See `schemas.models.FineTuneRequest` / `FineTuneResponse` for field docs.
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
