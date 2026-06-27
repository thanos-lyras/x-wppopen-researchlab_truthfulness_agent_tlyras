"""Minimal GCS service: get-or-create bucket + upload a file → returns gs:// URI."""

import os
from pathlib import Path

from dotenv import set_key
from google.cloud import storage

from mcp_server.utils import config


class GCSService:
    """Get-or-create a GCS bucket and upload local files, returning their gs:// URIs."""

    def __init__(self, bucket_name: str | None = None):
        """Resolve the bucket name (arg → env → auto-default), then ensure it exists.

        If neither `bucket_name` nor `GCS_BUCKET` is set, derives a default of
        `truthfulness-sft-<project-id>` (globally unique because project IDs are),
        persists it to .env, and updates os.environ so subsequent calls see it.
        """
        self.bucket_name = bucket_name or os.environ.get("GCS_BUCKET") or self._default_name()
        if not self.bucket_name:
            raise RuntimeError(
                "Can't resolve a GCS bucket — set GCS_BUCKET in .env or "
                "GOOGLE_CLOUD_PROJECT so we can derive a default."
            )

        self.client = storage.Client(project=config.PROJECT_ID)
        try:
            self.bucket = self.client.get_bucket(self.bucket_name)
        except Exception:
            # First-run bootstrap — Vertex SFT needs the bucket to exist before upload.
            print(f"Creating bucket {self.bucket_name} in {config.LOCATION}...")
            self.bucket = self.client.create_bucket(self.bucket_name, location=config.LOCATION)

    @staticmethod
    def _default_name() -> str | None:
        """Build a sane default bucket name from the project id and persist it.

        Bucket-name constraints: globally unique, 3-63 chars, lowercase [a-z0-9._-],
        cannot start/end with `-` or `.`. Sanitize legacy project-id chars (`.`, `:`).
        """
        if not config.PROJECT_ID:
            return None
        safe = config.PROJECT_ID.replace(".", "-").replace(":", "-")
        name = f"truthfulness-sft-{safe}"
        print(f"GCS_BUCKET unset — defaulting to {name} (writing to .env)")
        set_key(".env", "GCS_BUCKET", name, quote_mode="never")
        os.environ["GCS_BUCKET"] = name  # so subsequent reads in this process see it
        return name

    def upload(self, local: Path, gcs_path: str) -> str:
        """Upload `local` to `gs://<bucket>/<gcs_path>` and return the full gs:// URI."""
        blob = self.bucket.blob(gcs_path)
        blob.upload_from_filename(str(local))
        uri = f"gs://{self.bucket_name}/{gcs_path}"
        print(f"uploaded {local} → {uri}")
        return uri
