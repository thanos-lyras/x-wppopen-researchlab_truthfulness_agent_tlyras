"""Build the container image for the unified truthfulness stack.

Called from terraform/main.tf as part of `terraform apply` (via the
`null_resource.build_image` local-exec). Does ONLY the build — Terraform
owns the Cloud Run service definition + URL output.

Args (positional):
  project   GCP project ID
  region    GCP region (e.g. us-central1)
  image     Full image URI (region-docker.pkg.dev/PROJECT/REPO/SERVICE:TAG)
"""

from __future__ import annotations

import argparse
import subprocess

REPO = "cloud-run-source-deploy"


def run(*args: str) -> None:
    print(f"$ {' '.join(args)}")
    subprocess.run(args, check=True)


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("project")
    p.add_argument("region")
    p.add_argument("image")
    args = p.parse_args()

    print(f"▶ ensure repo {REPO} in {args.region}")
    if subprocess.run(
        ["gcloud", "artifacts", "repositories", "describe", REPO,
         f"--location={args.region}", f"--project={args.project}"],
        capture_output=True,
    ).returncode != 0:
        run("gcloud", "artifacts", "repositories", "create", REPO,
            "--repository-format=docker",
            f"--location={args.region}", f"--project={args.project}")

    print(f"▶ build {args.image}")
    run("gcloud", "builds", "submit",
        f"--project={args.project}",
        "--config=cloudbuild.unified.yaml",
        f"--substitutions=_IMAGE_TAG={args.image}", ".")


if __name__ == "__main__":
    main()
