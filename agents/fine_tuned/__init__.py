"""Agent bootstrap.

`adk web agents/fine_tuned` imports this package directly, so the auth env
vars must be set here — the parent `agents/__init__.py` may not run.
"""

import os

import google.auth

_, _project_id = google.auth.default()
os.environ.setdefault("GOOGLE_CLOUD_PROJECT", _project_id)
os.environ.setdefault("GOOGLE_CLOUD_LOCATION", "global")
os.environ.setdefault("GOOGLE_GENAI_USE_VERTEXAI", "True")
