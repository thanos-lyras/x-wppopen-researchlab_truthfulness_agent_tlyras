"""Minimal GCS service: get-or-create bucket + upload a file → returns gs:// URI."""

from pathlib import Path

from google.cloud import storage

from . import config


class GCSService:
    """Get-or-create a GCS bucket and upload local files, returning their gs:// URIs."""

    def __init__(self, bucket_name: str | None = None):
        """Resolve the bucket from arg or env, create it in GCS_LOCATION on first use if missing."""
        self.bucket_name = bucket_name or config.GCS_BUCKET
        if not self.bucket_name:
            raise RuntimeError("GCS_BUCKET env var not set")
        self.client = storage.Client(project=config.PROJECT_ID)
        try:
            self.bucket = self.client.get_bucket(self.bucket_name)
        except Exception:
            # First-run bootstrap — Vertex SFT needs the bucket to exist before upload.
            print(f"Creating bucket {self.bucket_name} in {config.GCS_LOCATION}...")
            self.bucket = self.client.create_bucket(self.bucket_name, location=config.GCS_LOCATION)

    def upload(self, local: Path, gcs_path: str) -> str:
        """Upload `local` to `gs://<bucket>/<gcs_path>` and return the full gs:// URI."""
        blob = self.bucket.blob(gcs_path)
        blob.upload_from_filename(str(local))
        uri = f"gs://{self.bucket_name}/{gcs_path}"
        print(f"uploaded {local} → {uri}")
        return uri
