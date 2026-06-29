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

from schemas.models import (
    ExplainedPrediction,
    ExplainRequest,
    ExplainResponse,
    Point,
    PredictRequest,
)
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


def _explain_one(point: Point, prediction: bool) -> str:
    """One free-form call per (statement, verdict) pair."""
    verdict = "True (truthful)" if prediction else "False (untruthful)"
    lines = [f"Statement: {point.statement}", f"Verdict: {verdict}"]
    for label, key in _METADATA_FIELDS:
        value = getattr(point, key)
        if value:
            lines.append(f"{label}: {value}")
    response = client.models.generate_content(
        model=EXPLAINER_MODEL,
        contents="\n".join(lines) + "\n\nExplain in 2-3 sentences.",
        config=_gen_config,
    )
    return response.text.strip()


def explain_truthfulness(req: ExplainRequest) -> ExplainResponse:
    """Classify each statement and explain the verdict.

    See `schemas.models.ExplainRequest` / `ExplainResponse` for field-level docs.

    Behavior summary:
    - Verdicts come from `predict_truthfulness` (zero-shot or fine-tuned, by `req.use_fine_tuned`).
    - Per-point explanations come from EXPLAINER_MODEL (independent, free-form).
    - `req.labels` supplied → response includes a `metrics` block on the underlying predictions.
    """
    pred = predict_truthfulness(
        PredictRequest(points=req.points, use_fine_tuned=req.use_fine_tuned, labels=req.labels)
    )
    results = [
        ExplainedPrediction(prediction=v, explanation=_explain_one(p, v))
        for p, v in zip(req.points, pred.predictions)
    ]
    return ExplainResponse(results=results, metrics=pred.metrics)


explain_truthfulness_tool = FunctionTool(explain_truthfulness)
