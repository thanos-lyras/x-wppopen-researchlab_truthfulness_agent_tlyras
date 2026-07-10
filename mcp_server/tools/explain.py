"""`explain_truthfulness` MCP tool — verdict from predict + free-form explanation from EXPLAINER_MODEL."""

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
    """Classify each statement and explain the verdict. See `schemas.models` for field docs."""
    pred = predict_truthfulness(
        PredictRequest(points=req.points, use_fine_tuned=req.use_fine_tuned, labels=req.labels)
    )
    results = [
        ExplainedPrediction(prediction=v, explanation=_explain_one(p, v))
        for p, v in zip(req.points, pred.predictions)
    ]
    return ExplainResponse(results=results, metrics=pred.metrics)


explain_truthfulness_tool = FunctionTool(explain_truthfulness)


def explain_truthfulness_from_gcs(uri: str, use_fine_tuned: bool | None = None) -> ExplainResponse:
    """Same as explain_truthfulness but reads the ExplainRequest JSON from a gs:// URI.

    `use_fine_tuned` overrides the value in the file — pass True/False to force,
    or None to defer to the file (defaults to zero-shot).
    """
    from services.gcs_service import GCSService
    data = GCSService().download_bytes(uri)
    req = ExplainRequest.model_validate_json(data)
    if use_fine_tuned is not None:
        req.use_fine_tuned = use_fine_tuned
    return explain_truthfulness(req)


explain_truthfulness_from_gcs_tool = FunctionTool(explain_truthfulness_from_gcs)
