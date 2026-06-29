"""Shared config for the fine-tuning services."""

import os
from pathlib import Path

# Paths
DATA_CSV = Path(os.environ.get(
    "TRUTHFULNESS_CSV",
    "/Users/thanos.lyras/Desktop/Satalia-projects/internal/data science challenge with agents/data.csv",
))
SPLITS_DIR = Path("data/splits")

# Split
SEED = 42

# Label mapping (6-way → binary)
LABEL_MAP = {
    "true":             1,
    "mostly-true":      1,
    "half-true":        1,
    "barely-true":      0,
    "false":            0,
    "extremely-false":  0,
}
TARGET_TOKEN = {1: "True", 0: "False"}

# SFT hyperparameters
BASE_MODEL    = os.environ.get("FINE_TUNED_BASE_MODEL", "gemini-2.5-flash-lite")
N_EPOCHS      = int(os.environ.get("FINE_TUNED_EPOCHS", "5"))
ADAPTER_SIZE  = os.environ.get("FINE_TUNED_ADAPTER_SIZE", "ADAPTER_SIZE_SIXTEEN")
LRM           = float(os.environ.get("FINE_TUNED_LRM", "1.0"))

# FINE_TUNED_MODEL is NOT read at import time — predict_fine_tuned and
# check_finetune_status read os.environ.get("FINE_TUNED_MODEL") at call time so
# updates from check_finetune_status take effect without an MCP server restart.
# Docs / example file: see .env.example.

# Last tuning job submitted — written automatically by TuningManager.submit()
# so `check_finetune_status` can poll it later without the user re-typing the name.
LAST_TUNING_JOB = os.environ.get("LAST_TUNING_JOB")

# GCP / Vertex — one project + one region for everything (Vertex client, GCS bucket,
# SFT jobs, tuned endpoint). Must be a real region, NOT "global" — Vertex SFT and
# GCS bucket creation both reject "global".
PROJECT_ID = os.environ.get("GOOGLE_CLOUD_PROJECT")
LOCATION   = os.environ.get("GOOGLE_CLOUD_LOCATION", "us-central1")
GCS_BUCKET = os.environ.get("GCS_BUCKET")

# Prompt
SYSTEM_INSTRUCTION = """You are an expert political fact-checker.

Given a statement, decide whether it is truthful (True) or untruthful (False)
using your own prior knowledge — no retrieval.

Map the six-way human label space onto the binary target:
- True  ← true, mostly-true, half-true
- False ← barely-true, false, extremely-false

Reply with a single word and nothing else: True or False.
"""
