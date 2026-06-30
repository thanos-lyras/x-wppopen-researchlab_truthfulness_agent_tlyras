"""Minimal GCS service: get-or-create bucket + upload/download/delete files."""

import os
from pathlib import Path

from google.cloud import storage


class GCSService:
    """Get-or-create a GCS bucket and move bytes/files to and from it.

    Reads `GCS_BUCKET`, `GCS_LOCATION`, and `GOOGLE_CLOUD_PROJECT` from env
    directly (no dependency on mcp_server.utils.config) so it can be used from
    any container — orchestrator, MCP, or scripts — without dragging in the MCP
    server package.
    """

    def __init__(self, bucket_name: str | None = None):
        """Resolve the bucket from arg or env; reference it via a Bucket proxy.

        Uses `client.bucket()` (no API call) instead of `client.get_bucket()`
        (which requires `storage.buckets.get`). Cloud Run runtime SAs typically
        have object-level perms (`storage.objects.{get,create,delete}`) on the
        bucket but not bucket-metadata perms; the proxy lets us upload/download
        without ever hitting the metadata path. The bucket must exist already —
        call `ensure_bucket_exists()` from a context that has IAM to bootstrap
        (e.g. an admin-run script), not from request-time code.
        """
        self.bucket_name = bucket_name or os.environ.get("GCS_BUCKET")
        if not self.bucket_name:
            raise RuntimeError("GCS_BUCKET env var not set")
        self.client = storage.Client(project=os.environ.get("GOOGLE_CLOUD_PROJECT"))
        self.bucket = self.client.bucket(self.bucket_name)

    def ensure_bucket_exists(self) -> None:
        """Create the bucket if it doesn't exist. Requires `storage.buckets.{get,create}`.

        Idempotent. Call from setup/bootstrap code (e.g. an SFT pipeline run by
        an admin SA); not from per-request code in Cloud Run, since runtime SAs
        don't have bucket-metadata perms.
        """
        location = os.environ.get("GCS_LOCATION", "us-central1")
        try:
            self.client.get_bucket(self.bucket_name)
        except Exception:
            print(f"Creating bucket {self.bucket_name} in {location}...")
            self.client.create_bucket(self.bucket_name, location=location)

    # ── file-based (used by SFT pipeline) ────────────────────────────────────

    def upload(self, local: Path, gcs_path: str) -> str:
        """Upload `local` to `gs://<bucket>/<gcs_path>` and return the full gs:// URI."""
        blob = self.bucket.blob(gcs_path)
        blob.upload_from_filename(str(local))
        uri = f"gs://{self.bucket_name}/{gcs_path}"
        print(f"uploaded {local} → {uri}")
        return uri

    # ── bytes-based (used by orchestrator /predict + MCP predict_from_gcs) ───

    def upload_bytes(self, data: bytes, gcs_path: str, content_type: str = "application/json") -> str:
        """Upload raw bytes to `gs://<bucket>/<gcs_path>`. Returns the full gs:// URI."""
        blob = self.bucket.blob(gcs_path)
        blob.upload_from_string(data, content_type=content_type)
        return f"gs://{self.bucket_name}/{gcs_path}"

    def download_bytes(self, uri: str) -> bytes:
        """Download the object at `gs://<bucket>/<path>` and return its bytes."""
        return self.bucket.blob(self._path_from_uri(uri)).download_as_bytes()

    def delete(self, uri: str) -> None:
        """Delete the object at `gs://<bucket>/<path>`. No-op if it doesn't exist."""
        self.bucket.blob(self._path_from_uri(uri)).delete(if_generation_match=None)

    def _path_from_uri(self, uri: str) -> str:
        """`gs://my-bucket/foo/bar.json` → `foo/bar.json`. Raises if bucket doesn't match self."""
        prefix = f"gs://{self.bucket_name}/"
        if not uri.startswith(prefix):
            raise ValueError(f"URI {uri!r} is not in bucket {self.bucket_name!r}")
        return uri[len(prefix):]
