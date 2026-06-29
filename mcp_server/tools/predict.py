"""`predict_truthfulness` MCP tool — unified zero-shot + fine-tuned predictor.

The `use_fine_tuned` flag picks the inference path:
- **False (default)**: zero-shot via `ZERO_SHOT_MODEL` (default `gemini-2.5-flash`)
  with the full-metadata prompt (statement + optional speaker / subjects /
  context fields).
- **True**: routes through the deployed tuned endpoint named in the
  `FINE_TUNED_MODEL` env var, with a statement-only prompt to match the v1 SFT
  training format. Falls back to `FINE_TUNED_BASE_MODEL` with a printed warning
  when `FINE_TUNED_MODEL` is unset, so the wiring stays smoke-testable before
  any SFT job has produced a tuned model.

When `labels` is provided, the response includes headline classification
metrics (accuracy / precision / recall / f1 / confusion matrix) treating True
as the positive class.
"""

from __future__ import annotations

import os

from google.adk.tools.function_tool import FunctionTool
from google.genai import types

from schemas.models import BinaryPrediction, Metrics, Point, PredictRequest, PredictResponse
from services.vertex_client import client

from ..utils import config
from ..utils.metrics import compute_metrics

# ── Zero-shot config ─────────────────────────────────────────────────────────
# `or` (not the default arg) so an explicitly empty value still falls back to the
# default instead of crashing the genai client with "model is required".
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

# ── Fine-tuned config ────────────────────────────────────────────────────────
# Uses the same system instruction that was baked into the SFT training records
# so train-time and serve-time prompts match (otherwise the tuned model degrades).
_fine_tuned_gen_config = types.GenerateContentConfig(
    system_instruction=config.SYSTEM_INSTRUCTION,
    temperature=0.0,
)


# ── Zero-shot helpers ────────────────────────────────────────────────────────
def _format_zero_shot_prompt(point: Point) -> str:
    """Multiline prompt: statement first, then any optional metadata fields present."""
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
    # Structured output: Gemini returns JSON conforming to BinaryPrediction
    # ({"verdict": true|false}). Pydantic parses and validates — no substring matching.
    return BinaryPrediction.model_validate_json(response.text).verdict


# ── Fine-tuned helpers ───────────────────────────────────────────────────────
def _resolve_fine_tuned_model() -> str:
    """Pick the tuned endpoint at call time; fall back to BASE_MODEL with a warning."""
    # Read os.environ on every call (not config.FINE_TUNED_MODEL which freezes at
    # module import) so check_finetune_status updates take effect without an MCP restart.
    model = os.environ.get("FINE_TUNED_MODEL")
    if model:
        return model
    print(
        f"⚠️  FINE_TUNED_MODEL not set — falling back to BASE_MODEL={config.BASE_MODEL}. "
        "Set FINE_TUNED_MODEL in .env (or run `make finetune`) to use the tuned model."
    )
    return config.BASE_MODEL


def _predict_fine_tuned(point: Point, model: str) -> bool:
    # Statement-only — matches the v1 SFT training format. Metadata fields on `point`
    # are intentionally ignored to keep train/serve prompts identical.
    response = client.models.generate_content(
        model=model,
        contents=point.statement,
        config=_fine_tuned_gen_config,
    )
    return response.text.strip().lower().startswith("true")


# ── Public entry ─────────────────────────────────────────────────────────────
def predict_truthfulness(req: PredictRequest) -> PredictResponse:
    """Classify a batch of statements as truthful (True) or untruthful (False).

    See `schemas.models.PredictRequest` / `PredictResponse` for field-level docs.

    Behavior summary:
    - `req.use_fine_tuned=False` → zero-shot via ZERO_SHOT_MODEL with metadata-enriched prompt.
    - `req.use_fine_tuned=True`  → tuned endpoint (FINE_TUNED_MODEL) with statement-only
      prompt; falls back to FINE_TUNED_BASE_MODEL with a warning if unset.
    - `req.labels` supplied → response includes a `metrics` block (treating True as positive).
    """
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
