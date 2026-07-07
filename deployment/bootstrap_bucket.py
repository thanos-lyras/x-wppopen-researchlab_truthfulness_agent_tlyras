#!/usr/bin/env python3
"""Idempotently create the GCS upload bucket + grant runtime SA object access.

Behavior:
- Reads `GOOGLE_CLOUD_PROJECT`, `GCS_BUCKET`, `GCS_LOCATION`, and
  `GOOGLE_CLOUD_LOCATION` from `.env`.
- If `GCS_BUCKET` is unset (fresh clone), generates a collision-safe default
  name `<project>-truthfulness-uploads-<region>` and WRITES it back to `.env`.
- If `GCS_LOCATION` is unset, falls back to `GOOGLE_CLOUD_LOCATION`, else
  `europe-west1`, and writes it back to `.env` too.
- Creates the bucket via `gcloud storage buckets create` if it doesn't exist.
- Grants the runtime compute SA (`<projnum>-compute@developer.gserviceaccount.com`)
  `roles/storage.objectAdmin` on the bucket.
- Safe to re-run: no-ops when everything is already provisioned.

Usage:
    python deployment/bootstrap_bucket.py

Or via the Makefile:
    make bootstrap-bucket
    make bootstrap                     # includes this as its final step

Why bucket creation lives here (not in `services/gcs_service.py`):
`GCSService.__init__` uses the lazy `client.bucket()` proxy so runtime SAs
only need `storage.objects.*` perms (not `storage.buckets.*`). That keeps
the runtime SA least-privilege but shifts the bucket-creation
responsibility to this operator-run script (which is expected to run
with wider ADC creds — typically a developer or admin).
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from dotenv import dotenv_values, set_key

REPO_ROOT = Path(__file__).resolve().parent.parent
ENV_FILE = REPO_ROOT / ".env"


def _env() -> dict[str, str]:
    return {k: (v or "") for k, v in dotenv_values(ENV_FILE).items()}


def _run_capture(cmd: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, capture_output=True, text=True)


def _run_stream(cmd: list[str]) -> None:
    subprocess.run(cmd, check=True)


def _project_number(project: str) -> str:
    """Fetch GCP project number — used to derive the default compute SA email."""
    result = subprocess.run(
        ["gcloud", "projects", "describe", project, "--format=value(projectNumber)"],
        check=True, capture_output=True, text=True,
    )
    return result.stdout.strip()


def _write_env(key: str, value: str) -> None:
    set_key(str(ENV_FILE), key, value, quote_mode="never")
    print(f"✅ Wrote {key}={value} to .env")


def _default_bucket_name(project: str, location: str) -> str:
    """`<project>-truthfulness-uploads-<region>` — collision-safe via project prefix."""
    return f"{project}-truthfulness-uploads-{location}"


def main() -> int:
    env = _env()
    project = env.get("GOOGLE_CLOUD_PROJECT")
    if not project:
        print("❌ GOOGLE_CLOUD_PROJECT not set in .env", file=sys.stderr)
        return 1

    # Resolve/generate GCS_LOCATION (write back to .env if we defaulted it).
    location = env.get("GCS_LOCATION") or env.get("GOOGLE_CLOUD_LOCATION") or "europe-west1"
    if not env.get("GCS_LOCATION"):
        _write_env("GCS_LOCATION", location)

    # Resolve/generate GCS_BUCKET (write back to .env if we defaulted it).
    bucket = env.get("GCS_BUCKET")
    if not bucket:
        bucket = _default_bucket_name(project, location)
        print(f"▶ GCS_BUCKET not set — using generated default: {bucket}")
        _write_env("GCS_BUCKET", bucket)

    print(f"▶ Bootstrapping gs://{bucket} in {location} for project {project}...")

    # 1. Create bucket if missing (idempotent).
    describe = _run_capture([
        "gcloud", "storage", "buckets", "describe",
        f"gs://{bucket}", f"--project={project}", "--format=value(name)",
    ])
    if describe.returncode == 0:
        print(f"✅ Bucket gs://{bucket} already exists.")
    else:
        print(f"▶ Creating gs://{bucket} (--location={location} --uniform-bucket-level-access)...")
        _run_stream([
            "gcloud", "storage", "buckets", "create", f"gs://{bucket}",
            f"--project={project}",
            f"--location={location}",
            "--uniform-bucket-level-access",
        ])
        print(f"✅ Created gs://{bucket}.")

    # 2. Grant the runtime compute SA `roles/storage.objectAdmin` (idempotent —
    # gcloud returns 0 when the binding already exists).
    projnum = _project_number(project)
    compute_sa = f"{projnum}-compute@developer.gserviceaccount.com"
    print(f"▶ Granting roles/storage.objectAdmin on gs://{bucket} to {compute_sa}...")
    _run_stream([
        "gcloud", "storage", "buckets", "add-iam-policy-binding", f"gs://{bucket}",
        f"--project={project}",
        f"--member=serviceAccount:{compute_sa}",
        "--role=roles/storage.objectAdmin",
    ])
    print(f"✅ Bucket + IAM ready. `/invoke` uploads can now write to gs://{bucket}/uploads/.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
