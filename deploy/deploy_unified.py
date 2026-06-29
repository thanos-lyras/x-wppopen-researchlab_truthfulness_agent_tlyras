"""Deploy the unified truthfulness stack (MCP + 4 Agents) to a single Cloud Run service.

Ensures the Artifact Registry repo exists, builds the image via Cloud Build
(Dockerfile.unified referenced from cloudbuild.unified.yaml), deploys with
`--allow-unauthenticated`, and writes UNIFIED_APP_URL back to .env.

Run via `make deploy-unified` (or `python -m deploy.deploy_unified`).
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys

from dotenv import dotenv_values, set_key

SERVICE = "truthfulness-unified"
REPO = "cloud-run-source-deploy"

# Keys / suffixes to exclude when shipping .env into the container:
# These will be set programmatically at runtime by unified_app.py
_EXCLUDE = {"MCP_SERVER_PORT", "MCP_SERVER_URL"}
_EXCLUDE_SUFFIXES = ("_A2A_PORT", "_A2A_URL")


def _gcloud(*args: str, capture: bool = False) -> str:
    """Run gcloud. Stream output by default; capture stdout when `capture=True`."""
    cmd = ["gcloud", *args]
    if capture:
        return subprocess.run(cmd, capture_output=True, text=True, check=True).stdout.strip()
    subprocess.run(cmd, check=True)
    return ""


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--project-id", default=os.getenv("GOOGLE_CLOUD_PROJECT"))
    p.add_argument("--region", default=os.getenv("GOOGLE_CLOUD_LOCATION", "us-central1"))
    p.add_argument("--env-file", default=".env")
    args = p.parse_args()
    if not args.project_id:
        sys.exit("❌ --project-id or GOOGLE_CLOUD_PROJECT required")

    project, region = args.project_id, args.region
    image = f"{region}-docker.pkg.dev/{project}/{REPO}/{SERVICE}:latest"
    
    # Filter environment variables to ship to the container
    env_vars = {
        k: v for k, v in dotenv_values(args.env_file).items()
        if v and k not in _EXCLUDE and not any(k.endswith(s) for s in _EXCLUDE_SUFFIXES)
    }
    print(f"▶ Deploying {SERVICE} to {region} ({project}) with {len(env_vars)} env vars")

    # 1. Artifact Registry repo (idempotent — describe then create only if missing).
    if subprocess.run(
        ["gcloud", "artifacts", "repositories", "describe", REPO,
         f"--location={region}", f"--project={project}"],
        capture_output=True,
    ).returncode != 0:
        _gcloud("artifacts", "repositories", "create", REPO,
                "--repository-format=docker", f"--location={region}", f"--project={project}")

    # 2. Cloud Build → image in Artifact Registry.
    _gcloud("builds", "submit", f"--project={project}",
            "--config=cloudbuild.unified.yaml", f"--substitutions=_IMAGE_TAG={image}", ".")

    # 3. Cloud Run deploy with public access → capture URL.
    url = _gcloud(
        "run", "deploy", SERVICE,
        f"--image={image}", f"--region={region}", f"--project={project}",
        "--allow-unauthenticated",
        f"--set-env-vars={','.join(f'{k}={v}' for k, v in env_vars.items())}",
        "--format=value(status.url)",
        capture=True,
    )

    set_key(args.env_file, "UNIFIED_APP_URL", url, quote_mode="never")
    print(f"\n✅ Deployed: {url}")
    print(f"✅ Wrote UNIFIED_APP_URL={url} to {args.env_file}")


if __name__ == "__main__":
    main()
