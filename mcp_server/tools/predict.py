"""`predict_truthfulness` tool — exposed via MCP.

Pure-LLM zero-shot classifier. Same logic that previously lived in
`agents/zero_shot/tools.py`, now owned by the MCP server so any
MCP-compatible client (our agents, Claude Desktop, Cursor, …) can call it.
"""

from __future__ import annotations

import os

from google import genai
from google.adk.tools.function_tool import FunctionTool
from google.genai import types

_MODEL = os.environ.get("ZERO_SHOT_MODEL", "gemini-2.5-flash")

_SYSTEM_INSTRUCTION = """You are an expert political fact-checker.

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

_client = genai.Client(vertexai=True)
_config = types.GenerateContentConfig(
    system_instruction=_SYSTEM_INSTRUCTION,
    temperature=0.0,
)


def _format_prompt(point: dict) -> str:
    lines = [f"Statement: {point['statement']}"]
    for label, key in _METADATA_FIELDS:
        value = point.get(key)
        if value:
            lines.append(f"{label}: {value}")
    return "\n".join(lines)


def _predict_one(point: dict) -> bool:
    response = _client.models.generate_content(
        model=_MODEL,
        contents=_format_prompt(point),
        config=_config,
    )
    return response.text.strip().lower().startswith("true")


def predict_truthfulness(points: list[dict]) -> list[bool]:
    """Classify a batch of statements as truthful (True) or untruthful (False).

    Args:
        points: List of statements with optional metadata. Each item supports
            the keys: statement (required), subjects, speaker_name, speaker_job,
            speaker_state, speaker_affiliation, statement_context.

    Returns:
        One bool per input point, in order. True = truthful, False = untruthful.
    """
    return [_predict_one(point) for point in points]


predict_truthfulness_tool = FunctionTool(predict_truthfulness)
