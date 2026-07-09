"""Agent bootstrap — re-runs the ADC / env setup because `adk web agents/explainer` skips the parent package."""

import os
import google.auth

_, _project_id = google.auth.default()
os.environ.setdefault("GOOGLE_CLOUD_PROJECT", _project_id)
os.environ.setdefault("GOOGLE_CLOUD_LOCATION", "global")
os.environ.setdefault("GOOGLE_GENAI_USE_VERTEXAI", "True")
