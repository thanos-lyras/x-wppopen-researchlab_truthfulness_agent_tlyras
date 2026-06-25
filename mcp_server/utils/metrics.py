"""Binary classification metrics for the truthfulness predictors.

Pure-function helper called by `predict_truthfulness` (both zero-shot and
fine-tuned paths). True is the positive class.
"""

from __future__ import annotations

from sklearn.metrics import (
    accuracy_score,
    confusion_matrix,
    precision_recall_fscore_support,
)


def compute_metrics(predictions: list[bool], labels: list[bool]) -> dict:
    """Compare predictions to ground-truth labels and return headline scores.

    Args:
        predictions: Model outputs (True = truthful, False = untruthful).
        labels: Ground-truth labels in the same order.

    Returns:
        Dict with `accuracy`, `precision`, `recall`, `f1`, `support`, and a
        `confusion_matrix` sub-dict with `tp`, `fn`, `fp`, `tn`. Precision /
        recall / f1 treat True as the positive class.

    Raises:
        ValueError: predictions and labels differ in length.
    """
    if len(predictions) != len(labels):
        raise ValueError(
            f"length mismatch: predictions={len(predictions)}, labels={len(labels)}"
        )

    tn, fp, fn, tp = confusion_matrix(
        labels, predictions, labels=[False, True]
    ).ravel()
    prec, rec, f1, _ = precision_recall_fscore_support(
        labels, predictions, average="binary", pos_label=True, zero_division=0
    )
    return {
        "accuracy": float(accuracy_score(labels, predictions)),
        "precision": float(prec),
        "recall": float(rec),
        "f1": float(f1),
        "support": len(labels),
        "confusion_matrix": {
            "tp": int(tp),
            "fn": int(fn),
            "fp": int(fp),
            "tn": int(tn),
        },
    }
