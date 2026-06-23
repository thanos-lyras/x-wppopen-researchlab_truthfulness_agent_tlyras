"""`predict_fine_tuned_truthfulness` MCP tool — same shape as `predict_truthfulness`
but routes inference through the fine-tuned model resource set in `FINE_TUNED_MODEL`.

When `FINE_TUNED_MODEL` is unset, falls back to `BASE_MODEL` so the tool stays
callable for smoke tests before the first SFT job has produced a tuned model.

Statement-only prompt to match the v1 SFT training format.
"""

from __future__ import annotations

import os

from google import genai
from google.adk.tools.function_tool import FunctionTool
from google.genai import types

from ..utils import config

_client = genai.Client(
    vertexai=True, project=config.PROJECT_ID, location=config.TUNING_LOCATION
)
_gen_config = types.GenerateContentConfig(
    system_instruction=config.SYSTEM_INSTRUCTION,
    temperature=0.0,
)


def _resolve_model() -> str:
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


def _predict_one(statement: str, model: str) -> bool:
    response = _client.models.generate_content(
        model=model,
        contents=statement,
        config=_gen_config,
    )
    return response.text.strip().lower().startswith("true")


def predict_fine_tuned_truthfulness(points: list[dict]) -> list[bool]:
    """Classify a batch of statements using the FINE-TUNED Gemini model.

    Mirrors the v1 SFT training format (statement-only — metadata columns are NOT
    included in the prompt). For a fair comparison against the zero-shot baseline,
    the zero-shot tool should also call with statement-only inputs.

    If `FINE_TUNED_MODEL` is unset, falls back to `BASE_MODEL` and emits a warning
    so the tool remains callable for end-to-end smoke tests.

    Args:
        points: List of statements. Each item is a dict with at least `statement`.
            Other fields are ignored in v1.

    Returns:
        One bool per input point, in order. True = truthful, False = untruthful.
    """
    model = _resolve_model()
    return [_predict_one(p["statement"], model) for p in points]


predict_fine_tuned_truthfulness_tool = FunctionTool(predict_fine_tuned_truthfulness)
