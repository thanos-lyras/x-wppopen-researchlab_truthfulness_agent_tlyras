"""`predict_fine_tuned_truthfulness` MCP tool — same shape as `predict_truthfulness`
but routes inference through the fine-tuned model resource set in `FINE_TUNED_MODEL`.

Statement-only prompt to match the v1 SFT training format.
"""

from __future__ import annotations

from google import genai
from google.adk.tools.function_tool import FunctionTool
from google.genai import types

from ..utils import config

if not config.FINE_TUNED_MODEL:
    # Defer the error until first call so the MCP server can still register the tool.
    _client = None
    _gen_config = None
else:
    _client = genai.Client(
        vertexai=True, project=config.PROJECT_ID, location=config.TUNING_LOCATION
    )
    _gen_config = types.GenerateContentConfig(
        system_instruction=config.SYSTEM_INSTRUCTION,
        temperature=0.0,
    )


def _predict_one(statement: str) -> bool:
    response = _client.models.generate_content(
        model=config.FINE_TUNED_MODEL,
        contents=statement,
        config=_gen_config,
    )
    return response.text.strip().lower().startswith("true")


def predict_fine_tuned_truthfulness(points: list[dict]) -> list[bool]:
    """Classify a batch of statements using the FINE-TUNED Gemini model.

    Mirrors the v1 SFT training format (statement-only — metadata columns are NOT
    included in the prompt). For a fair comparison against the zero-shot baseline,
    the zero-shot tool should also call with statement-only inputs.

    Args:
        points: List of statements. Each item is a dict with at least `statement`.
            Other fields are ignored in v1.

    Returns:
        One bool per input point, in order. True = truthful, False = untruthful.
    """
    if not config.FINE_TUNED_MODEL:
        raise RuntimeError(
            "FINE_TUNED_MODEL env var not set — paste the tuned-model resource name "
            "(projects/.../models/<id>) from the Vertex AI Tuning Studio into .env."
        )
    return [_predict_one(p["statement"]) for p in points]


predict_fine_tuned_truthfulness_tool = FunctionTool(predict_fine_tuned_truthfulness)
