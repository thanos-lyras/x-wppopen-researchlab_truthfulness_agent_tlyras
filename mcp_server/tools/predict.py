"""`predict_truthfulness` MCP tool — unified zero-shot + fine-tuned predictor."""

from __future__ import annotations
import os
from google.adk.tools.function_tool import FunctionTool
from google.genai import types
from schemas.models import BinaryPrediction, Metrics, Point, PredictRequest, PredictResponse
from services.vertex_client import client
from ..utils import config
from ..utils.metrics import compute_metrics

# ── Zero-shot config ────────────────────────────────────────────────────
_ZERO_SHOT_MODEL = os.environ.get("ZERO_SHOT_MODEL") or "gemini-2.5-flash"

_ZERO_SHOT_SYSTEM_INSTRUCTION = """You are an expert political fact-checker.

Given a statement (and optionally metadata about the speaker and context),
decide whether it is truthful or untruthful using your own prior knowledge —
no retrieval.

Map the six-way human label space onto the binary target:
- truthful   ← true, mostly-true, half-true
- untruthful ← barely-true, false, extremely-false

Return a JSON object with a single boolean field `verdict`:
- `{"verdict": true}`  for truthful
- `{"verdict": false}` for untruthful
"""

_METADATA_FIELDS = [
    ("Subjects", "subjects"),
    ("Speaker", "speaker_name"),
    ("Speaker job", "speaker_job"),
    ("Speaker state", "speaker_state"),
    ("Speaker affiliation", "speaker_affiliation"),
    ("Context", "statement_context"),
]

_zero_shot_gen_config = types.GenerateContentConfig(
    system_instruction=_ZERO_SHOT_SYSTEM_INSTRUCTION,
    temperature=0.0,
    response_mime_type="application/json",
    response_schema=BinaryPrediction,
)

# ── Fine-tuned config ───────────────────────────────────────────────────
# Uses the SFT training-time system prompt — train/serve prompts must match
# or the tuned model degrades.
_fine_tuned_gen_config = types.GenerateContentConfig(
    system_instruction=config.SYSTEM_INSTRUCTION,
    temperature=0.0,
)


def _format_zero_shot_prompt(point: Point) -> str:
    lines = [f"Statement: {point.statement}"]
    for label, key in _METADATA_FIELDS:
        value = getattr(point, key)
        if value:
            lines.append(f"{label}: {value}")
    return "\n".join(lines)


def _predict_zero_shot(point: Point) -> bool:
    response = client.models.generate_content(
        model=_ZERO_SHOT_MODEL,
        contents=_format_zero_shot_prompt(point),
        config=_zero_shot_gen_config,
    )
    return BinaryPrediction.model_validate_json(response.text).verdict


def _resolve_fine_tuned_model() -> str:
    # Read os.environ at call time (not config.FINE_TUNED_MODEL which freezes at import)
    # so check_finetune_status updates take effect without an MCP restart.
    model = os.environ.get("FINE_TUNED_MODEL")
    if model:
        return model
    print(
        f"⚠️  FINE_TUNED_MODEL not set — falling back to BASE_MODEL={config.BASE_MODEL}. "
        "Set FINE_TUNED_MODEL in .env (or run `make finetune`) to use the tuned model."
    )
    return config.BASE_MODEL


def _predict_fine_tuned(point: Point, model: str) -> bool:
    # Statement-only — matches the v1 SFT training format. Metadata fields are
    # intentionally ignored to keep train/serve prompts identical.
    response = client.models.generate_content(
        model=model,
        contents=point.statement,
        config=_fine_tuned_gen_config,
    )
    return response.text.strip().lower().startswith("true")


def predict_truthfulness(req: PredictRequest) -> PredictResponse:
    """Classify a batch as truthful (True) or untruthful (False). See `schemas.models` for field docs."""
    if req.use_fine_tuned:
        model = _resolve_fine_tuned_model()
        predictions = [_predict_fine_tuned(p, model) for p in req.points]
    else:
        predictions = [_predict_zero_shot(p) for p in req.points]

    metrics = (
        Metrics.model_validate(compute_metrics(predictions, req.labels))
        if req.labels is not None
        else None
    )
    return PredictResponse(predictions=predictions, metrics=metrics)


predict_truthfulness_tool = FunctionTool(predict_truthfulness)


def predict_truthfulness_from_gcs(uri: str, use_fine_tuned: bool | None = None) -> PredictResponse:
    """Same as predict_truthfulness but reads the PredictRequest JSON from a gs:// URI.

    `use_fine_tuned` overrides the value in the file — pass True/False to force,
    or None to defer to the file (defaults to zero-shot).
    """
    from services.gcs_service import GCSService
    data = GCSService().download_bytes(uri)
    req = PredictRequest.model_validate_json(data)
    if use_fine_tuned is not None:
        req.use_fine_tuned = use_fine_tuned
    return predict_truthfulness(req)


predict_truthfulness_from_gcs_tool = FunctionTool(predict_truthfulness_from_gcs)
