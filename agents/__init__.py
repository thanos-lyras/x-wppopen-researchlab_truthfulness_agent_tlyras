"""Package bootstrap.

Runs before any agent module is imported. Pulls GCP project/location from
gcloud Application Default Credentials so you don't have to hardcode them in
`.env`. Anything already set in the environment (e.g. via `.env`) wins.
"""

import os

import google.auth

_, _project_id = google.auth.default()
os.environ.setdefault("GOOGLE_CLOUD_PROJECT", _project_id)
os.environ.setdefault("GOOGLE_CLOUD_LOCATION", "global")
os.environ.setdefault("GOOGLE_GENAI_USE_VERTEXAI", "True")
