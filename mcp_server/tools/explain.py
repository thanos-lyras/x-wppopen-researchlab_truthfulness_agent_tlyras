"""`explain_truthfulness` MCP tool — predict + explain in one call.

Composes `predict_truthfulness` to get the verdict (zero-shot or fine-tuned,
chosen by `use_fine_tuned`), then asks an independent free-form model
(`EXPLAINER_MODEL`, default `gemini-2.5-flash`) to articulate the factors
driving each verdict. When `labels` are supplied, the response includes
headline metrics on the underlying predictions.
"""

from __future__ import annotations

import os

from google.adk.tools.function_tool import FunctionTool
from google.genai import types

from services.vertex_client import client

from .predict import predict_truthfulness

# `or` (not the default arg) so an explicitly empty value (e.g. EXPLAINER_MODEL=
# in a misconfigured deploy) still falls back to the default instead of crashing
# the genai client with "model is required".
EXPLAINER_MODEL = os.environ.get("EXPLAINER_MODEL") or "gemini-2.5-flash"

EXPLAINER_SYSTEM_INSTRUCTION = """You are a political fact-checking explainer.

Given a statement and a True/False verdict, articulate in 2-3 sentences the
key factors that drive the verdict — the concrete fact, claim, public record,
or domain knowledge that makes the statement likely true or false.

Be specific. Cite the concrete claim. Do not contradict the verdict; explain it.
"""

_METADATA_FIELDS = [
    ("Speaker", "speaker_name"),
    ("Speaker job", "speaker_job"),
    ("Speaker affiliation", "speaker_affiliation"),
    ("Context", "statement_context"),
    ("Subjects", "subjects"),
]

_gen_config = types.GenerateContentConfig(
    system_instruction=EXPLAINER_SYSTEM_INSTRUCTION,
    temperature=0.0,
)


def _explain_one(point: dict, prediction: bool) -> str:
    """One free-form call per (statement, verdict) pair."""
    verdict = "True (truthful)" if prediction else "False (untruthful)"
    lines = [f"Statement: {point['statement']}", f"Verdict: {verdict}"]
    for label, key in _METADATA_FIELDS:
        value = point.get(key)
        if value:
            lines.append(f"{label}: {value}")
    response = client.models.generate_content(
        model=EXPLAINER_MODEL,
        contents="\n".join(lines) + "\n\nExplain in 2-3 sentences.",
        config=_gen_config,
    )
    return response.text.strip()


def explain_truthfulness(
    points: list[dict],
    use_fine_tuned: bool = False,
    labels: list[bool] | None = None,
) -> dict:
    """Classify each statement and explain the verdict.

    Args:
        points: List of statements. Each item is a dict with at least
            `statement` (plus optional speaker/subjects/context metadata
            used in both the predictor and the explainer prompts).
        use_fine_tuned: Which predictor produces the verdicts. False (default)
            = zero-shot model; True = the deployed tuned endpoint (falls back
            to FINE_TUNED_BASE_MODEL with a warning if unset). The explainer
            model is independent.
        labels: Optional ground-truth booleans (one per point, same order).
            When provided, the response includes headline metrics on the
            underlying predictions (treating True as the positive class).

    Returns:
        Dict with:
        - `results`: list of `{"prediction": bool, "explanation": str}`,
          one per input point, in order.
        - `metrics`: dict (when `labels` is provided) or None.
    """
    pred = predict_truthfulness(points, use_fine_tuned=use_fine_tuned, labels=labels)
    predictions = pred["predictions"]
    explanations = [_explain_one(p, v) for p, v in zip(points, predictions)]
    results = [
        {"prediction": v, "explanation": e}
        for v, e in zip(predictions, explanations)
    ]
    return {"results": results, "metrics": pred["metrics"]}


explain_truthfulness_tool = FunctionTool(explain_truthfulness)
