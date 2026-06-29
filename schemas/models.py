"""Pydantic models for tool I/O and LLM structured output.

All models live here. Import as `from schemas.models import PredictRequest, ...`.

Sections:
- Shared           : Point, ConfusionMatrix, Metrics
- predict tool     : PredictRequest, PredictResponse
- explain tool     : ExplainRequest, ExplainedPrediction, ExplainResponse
- finetune tool    : FineTuneRequest, SplitCounts, FineTuneResponse
- status tool      : NoJobResponse, JobStatusResponse
- LLM output       : BinaryPrediction
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


# ── Shared ────────────────────────────────────────────────────────────────


class Point(BaseModel):
    """A single statement to classify, with optional metadata fields."""

    statement: str = Field(description="The claim to classify.")
    subjects: str | None = Field(
        default=None,
        description="Comma-separated topics the statement touches on (e.g. 'health-care,medicare'). Used by the zero-shot predictor only.",
    )
    speaker_name: str | None = Field(
        default=None,
        description="Full name of the person making the statement. Used by the zero-shot predictor only.",
    )
    speaker_job: str | None = Field(
        default=None,
        description="Speaker's job title or role at the time of the statement.",
    )
    speaker_state: str | None = Field(
        default=None,
        description="US state the speaker is associated with.",
    )
    speaker_affiliation: str | None = Field(
        default=None,
        description="Political party or organization the speaker belongs to.",
    )
    statement_context: str | None = Field(
        default=None,
        description="Where / when the statement was made (interview, speech, tweet, etc.).",
    )


class ConfusionMatrix(BaseModel):
    """Binary confusion matrix counts (True = positive class)."""

    tp: int = Field(description="True positives — predicted True, actually True.")
    fn: int = Field(description="False negatives — predicted False, actually True.")
    fp: int = Field(description="False positives — predicted True, actually False.")
    tn: int = Field(description="True negatives — predicted False, actually False.")


class Metrics(BaseModel):
    """Headline binary classification metrics."""

    accuracy: float = Field(description="Fraction of correct predictions over all points.")
    precision: float = Field(
        description="TP / (TP + FP). 0.0 when no positive predictions were made.",
    )
    recall: float = Field(
        description="TP / (TP + FN). 0.0 when no actual positives exist.",
    )
    f1: float = Field(description="Harmonic mean of precision and recall.")
    support: int = Field(description="Number of points scored (equals len(predictions)).")
    confusion_matrix: ConfusionMatrix = Field(description="Breakdown of TP / FN / FP / TN counts.")


# ── predict tool ──────────────────────────────────────────────────────────


class PredictRequest(BaseModel):
    """Input for predict_truthfulness."""

    points: list[Point] = Field(description="Batch of statements to classify.")
    use_fine_tuned: bool = Field(
        default=False,
        description="If True, route through the deployed tuned endpoint (FINE_TUNED_MODEL). False uses the zero-shot model (ZERO_SHOT_MODEL).",
    )
    labels: list[bool] | None = Field(
        default=None,
        description="Ground-truth booleans, one per point in the same order. Provide to get a `metrics` block in the response.",
    )


class PredictResponse(BaseModel):
    """Output of predict_truthfulness."""

    predictions: list[bool] = Field(description="Binary verdicts, one per input point, in order.")
    metrics: Metrics | None = Field(
        default=None,
        description="Headline metrics when ground-truth labels were supplied; None otherwise.",
    )


# ── explain tool ──────────────────────────────────────────────────────────


class ExplainRequest(BaseModel):
    """Input for explain_truthfulness — same signature as PredictRequest."""

    points: list[Point] = Field(description="Batch of statements to classify + explain.")
    use_fine_tuned: bool = Field(
        default=False,
        description="Which predictor produces the verdicts. The explainer model is independent.",
    )
    labels: list[bool] | None = Field(
        default=None,
        description="Ground-truth booleans, one per point in the same order. Provide to get a `metrics` block.",
    )


class ExplainedPrediction(BaseModel):
    """One classified statement plus its natural-language explanation."""

    prediction: bool = Field(description="Truthfulness verdict for the statement.")
    explanation: str = Field(
        description="2-3 sentence rationale citing the concrete fact or claim that drives the verdict.",
    )


class ExplainResponse(BaseModel):
    """Output of explain_truthfulness."""

    results: list[ExplainedPrediction] = Field(description="Per-point verdict + explanation, in input order.")
    metrics: Metrics | None = Field(
        default=None,
        description="Headline metrics when ground-truth labels were supplied; None otherwise.",
    )


# ── finetune tool ─────────────────────────────────────────────────────────


class FineTuneRequest(BaseModel):
    """Input for fine_tune_truthfulness."""

    csv_path: str | None = Field(
        default=None,
        description="Optional override for the source CSV. Defaults to TRUTHFULNESS_CSV (data/data.csv).",
    )
    wait: bool = Field(
        default=False,
        description="If True, block until the SFT job reaches a terminal state (30-90 min). If False, return after submission and rely on check_finetune_status to poll.",
    )


class SplitCounts(BaseModel):
    """Row counts per split from the stratified 80/10/10 prepare step."""

    train: int = Field(description="Number of rows in the training split.")
    val: int = Field(description="Number of rows in the validation split.")
    test: int = Field(description="Number of rows in the held-out test split.")


class FineTuneResponse(BaseModel):
    """Output of fine_tune_truthfulness."""

    split: SplitCounts = Field(description="Row counts produced by the prepare step.")
    train_gcs_uri: str = Field(description="gs:// URI of the uploaded training JSONL.")
    val_gcs_uri: str = Field(description="gs:// URI of the uploaded validation JSONL.")
    job_name: str = Field(description="Vertex tuning job resource name. Persisted to LAST_TUNING_JOB in .env.")
    state: str = Field(description="Job state at the time of return (e.g. JOB_STATE_RUNNING).")
    tuned_model: str | None = Field(
        default=None,
        description="Deployed endpoint resource name when wait=True and job succeeded; None otherwise.",
    )


# ── status tool ───────────────────────────────────────────────────────────


class NoJobResponse(BaseModel):
    """Returned when no SFT job has been submitted yet."""

    status: Literal["no_job"] = Field(description="Literal 'no_job' signaling that LAST_TUNING_JOB is unset.")
    message: str = Field(description="Human-readable summary.")


class JobStatusResponse(BaseModel):
    """Returned when a job exists — includes endpoint when SUCCEEDED."""

    job_name: str = Field(description="The polled Vertex tuning job resource name.")
    state: str = Field(description="Current JobState name (e.g. JOB_STATE_RUNNING, JOB_STATE_SUCCEEDED).")
    endpoint: str | None = Field(
        default=None,
        description="Deployed endpoint path. Only set when state is JOB_STATE_SUCCEEDED.",
    )
    endpoint_updated: bool = Field(
        description="True if .env was just rewritten this call (FINE_TUNED_MODEL changed).",
    )
    message: str = Field(description="Human-readable summary suitable for surfacing to the user.")


# ── LLM structured output ────────────────────────────────────────────────


class BinaryPrediction(BaseModel):
    """A single truthfulness verdict.

    Intended for `response_schema=BinaryPrediction` on a genai
    `generate_content` call — Gemini returns `{"verdict": true}` which
    Pydantic parses directly, no `response.text.strip().lower()` heuristic.
    """

    verdict: bool = Field(description="True for truthful statements, False for untruthful.")
