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

from services.vertex_client import client

from ..utils import config
from ..utils.metrics import compute_metrics

# ── Zero-shot config ─────────────────────────────────────────────────────────
_ZERO_SHOT_MODEL = os.environ.get("ZERO_SHOT_MODEL", "gemini-2.5-flash")

_ZERO_SHOT_SYSTEM_INSTRUCTION = """You are an expert political fact-checker.

Given a statement (and optionally metadata about the speaker and context),
decide whether it is truthful (True) or untruthful (False) using your own
prior knowledge — no retrieval.

Map the six-way human label space onto the binary target:
- True  ← true, mostly-true, half-true
- False ← barely-true, false, extremely-false

Reply with a single word and nothing else: True or False.
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
)

# ── Fine-tuned config ────────────────────────────────────────────────────────
# Uses the same system instruction that was baked into the SFT training records
# so train-time and serve-time prompts match (otherwise the tuned model degrades).
_fine_tuned_gen_config = types.GenerateContentConfig(
    system_instruction=config.SYSTEM_INSTRUCTION,
    temperature=0.0,
)


# ── Zero-shot helpers ────────────────────────────────────────────────────────
def _format_zero_shot_prompt(point: dict) -> str:
    """Multiline prompt: statement first, then any optional metadata fields present."""
    lines = [f"Statement: {point['statement']}"]
    for label, key in _METADATA_FIELDS:
        value = point.get(key)
        if value:
            lines.append(f"{label}: {value}")
    return "\n".join(lines)


def _predict_zero_shot(point: dict) -> bool:
    response = client.models.generate_content(
        model=_ZERO_SHOT_MODEL,
        contents=_format_zero_shot_prompt(point),
        config=_zero_shot_gen_config,
    )
    return response.text.strip().lower().startswith("true")


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


def _predict_fine_tuned(point: dict, model: str) -> bool:
    # Statement-only — matches the v1 SFT training format. Metadata fields on `point`
    # are intentionally ignored to keep train/serve prompts identical.
    response = client.models.generate_content(
        model=model,
        contents=point["statement"],
        config=_fine_tuned_gen_config,
    )
    return response.text.strip().lower().startswith("true")


# ── Public entry ─────────────────────────────────────────────────────────────
def predict_truthfulness(
    points: list[dict],
    use_fine_tuned: bool = False,
    labels: list[bool] | None = None,
) -> dict:
    """Classify a batch of statements as truthful (True) or untruthful (False).

    Args:
        points: List of statements. Each item is a dict with at least `statement`.
            In zero-shot mode, optional metadata fields enrich the prompt:
            `subjects`, `speaker_name`, `speaker_job`, `speaker_state`,
            `speaker_affiliation`, `statement_context`. In fine-tuned mode only
            `statement` is used (to match the v1 SFT training format).
        use_fine_tuned: When False (default), classify via the zero-shot model
            (`ZERO_SHOT_MODEL`, default `gemini-2.5-flash`). When True, route
            through the deployed tuned endpoint (`FINE_TUNED_MODEL`). If True
            and `FINE_TUNED_MODEL` is unset, falls back to `FINE_TUNED_BASE_MODEL`
            and emits a warning.
        labels: Optional ground-truth booleans (one per point, same order). When
            provided, the response includes headline metrics (accuracy, precision,
            recall, f1, confusion matrix) treating True as the positive class.

    Returns:
        Dict with:
        - `predictions`: List[bool], one per input point, in order.
        - `metrics`: dict (when `labels` is provided) or None.
    """
    if use_fine_tuned:
        model = _resolve_fine_tuned_model()
        predictions = [_predict_fine_tuned(p, model) for p in points]
    else:
        predictions = [_predict_zero_shot(p) for p in points]

    metrics = compute_metrics(predictions, labels) if labels is not None else None
    return {"predictions": predictions, "metrics": metrics}


predict_truthfulness_tool = FunctionTool(predict_truthfulness)
