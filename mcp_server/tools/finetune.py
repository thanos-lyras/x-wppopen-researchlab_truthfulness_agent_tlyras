"""`fine_tune_truthfulness` MCP tool — composes DatasetProcessor + GCSService + TuningManager."""

from __future__ import annotations
import io
from google.adk.tools.function_tool import FunctionTool
from schemas.models import FineTuneRequest, FineTuneResponse, SplitCounts
from services.gcs_service import GCSService
from ..utils import config
from ..utils.dataset_processor import DatasetProcessor
from ..utils.tuning_manager import TuningManager


def _submit_and_maybe_wait(paths: dict, wait: bool) -> FineTuneResponse:
    """Upload prepared splits to GCS → submit SFT → optionally block until terminal."""
    gcs = GCSService()
    train_uri = gcs.upload(paths["train"], f"finetuning/{config.BASE_MODEL}/train.jsonl")
    val_uri   = gcs.upload(paths["val"],   f"finetuning/{config.BASE_MODEL}/val.jsonl")

    tuning = TuningManager()
    job = tuning.submit(train_uri, val_uri)

    split = SplitCounts(**{k: sum(1 for _ in open(p)) for k, p in paths.items()})
    state = str(job.state)
    tuned_model: str | None = None

    if wait:
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


def fine_tune_truthfulness(req: FineTuneRequest) -> FineTuneResponse:
    """Prepare dataset (from filesystem CSV) → upload → submit Vertex SFT.

    See `schemas.models.FineTuneRequest` / `FineTuneResponse` for field docs.
    """
    paths = DatasetProcessor().prepare(req.csv_path)
    return _submit_and_maybe_wait(paths, req.wait)


fine_tune_truthfulness_tool = FunctionTool(fine_tune_truthfulness)


def fine_tune_truthfulness_from_gcs(uri: str, wait: bool = False) -> FineTuneResponse:
    """Download a CSV dataset from `uri` and submit an SFT job.

    Defaults to `wait=False` because SFT takes 30-90 min — a blocking call would
    trip A2A/gateway timeouts. Poll with `check_finetune_status` afterwards.
    """
    data = GCSService().download_bytes(uri)
    # pd.read_csv accepts a bytes buffer directly — no temp file, mirroring how
    # predict/explain_from_gcs pass bytes straight into Pydantic.
    paths = DatasetProcessor().prepare(io.BytesIO(data))
    return _submit_and_maybe_wait(paths, wait)


fine_tune_truthfulness_from_gcs_tool = FunctionTool(fine_tune_truthfulness_from_gcs)
