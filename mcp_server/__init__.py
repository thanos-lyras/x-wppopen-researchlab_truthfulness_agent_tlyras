"""MCP server bootstrap.

Mirrors `agents/__init__.py`: pulls GCP project/location from gcloud
Application Default Credentials so tool implementations that talk to
Vertex AI (e.g. the predict tool's `genai.Client(vertexai=True)`) don't
need them hardcoded in `.env`.
"""

import os

import google.auth

_, _project_id = google.auth.default()
os.environ.setdefault("GOOGLE_CLOUD_PROJECT", _project_id)
os.environ.setdefault("GOOGLE_CLOUD_LOCATION", "us-central1")
os.environ.setdefault("GOOGLE_GENAI_USE_VERTEXAI", "True")
