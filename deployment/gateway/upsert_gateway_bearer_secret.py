#!/usr/bin/env python3
"""Create or update the A2A gateway Bearer token in Google Secret Manager.

This script intentionally does not rotate on a schedule. It creates the secret
container if needed, then adds a new secret version when you explicitly run it.
"""

from __future__ import annotations

import argparse
import os
from pathlib import Path
import secrets
import shutil
import subprocess
import sys
from collections.abc import Sequence
from typing import Optional


def run(command: Sequence[str], *, input_text: Optional[str] = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        input=input_text,
        check=False,
        capture_output=True,
        text=True,
    )


def gcloud_ok(command: Sequence[str], *, input_text: Optional[str] = None) -> bool:
    result = run(command, input_text=input_text)
    if result.returncode == 0:
        return True
    if result.stderr:
        print(result.stderr.strip(), file=sys.stderr)
    return False


def resolve_gcloud(explicit_path: Optional[str] = None) -> str:
    """Resolve the gcloud executable across Windows shells and Git Bash."""

    candidates = [explicit_path] if explicit_path else ["gcloud", "gcloud.cmd", "gcloud.exe"]
    for candidate in candidates:
        if not candidate:
            continue
        found = shutil.which(candidate)
        if found:
            return found
        candidate_path = Path(candidate).expanduser()
        if candidate_path.exists():
            return str(candidate_path)

    local_app_data = os.environ.get("LOCALAPPDATA")
    common_paths = []
    if local_app_data:
        common_paths.append(
            Path(local_app_data) / "Google" / "Cloud SDK" / "google-cloud-sdk" / "bin" / "gcloud.cmd",
        )
    common_paths.extend(
        [
            Path("C:/Program Files/Google/Cloud SDK/google-cloud-sdk/bin/gcloud.cmd"),
            Path("C:/Program Files (x86)/Google/Cloud SDK/google-cloud-sdk/bin/gcloud.cmd"),
        ],
    )
    for candidate_path in common_paths:
        if candidate_path.exists():
            return str(candidate_path)

    raise SystemExit(
        "Could not find gcloud. Install the Google Cloud SDK, add it to PATH, or pass --gcloud C:/path/to/gcloud.cmd.",
    )


def ensure_secret(project_id: str, secret_id: str, gcloud: str) -> None:
    describe = [
        gcloud,
        "secrets",
        "describe",
        secret_id,
        "--project",
        project_id,
        "--format=value(name)",
    ]
    if gcloud_ok(describe):
        return

    create = [
        gcloud,
        "secrets",
        "create",
        secret_id,
        "--project",
        project_id,
        "--replication-policy=automatic",
    ]
    if not gcloud_ok(create):
        raise SystemExit(f"Failed to create secret {secret_id!r} in project {project_id!r}")


def add_secret_version(project_id: str, secret_id: str, token: str, gcloud: str) -> None:
    command = [
        gcloud,
        "secrets",
        "versions",
        "add",
        secret_id,
        "--project",
        project_id,
        "--data-file=-",
    ]
    if not gcloud_ok(command, input_text=token):
        raise SystemExit(f"Failed to add a new version to secret {secret_id!r}")


def grant_accessor(project_id: str, secret_id: str, service_account: str, gcloud: str) -> None:
    command = [
        gcloud,
        "secrets",
        "add-iam-policy-binding",
        secret_id,
        "--project",
        project_id,
        "--member",
        f"serviceAccount:{service_account}",
        "--role",
        "roles/secretmanager.secretAccessor",
    ]
    if not gcloud_ok(command):
        raise SystemExit(f"Failed to grant secretAccessor on {secret_id!r} to {service_account!r}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", required=True, help="GCP project ID")
    parser.add_argument(
        "--secret-id",
        default="a2a-gateway-bearer-token",
        help="Secret Manager secret ID to create/update",
    )
    parser.add_argument(
        "--token",
        help="Bearer token value. If omitted, a 64-byte URL-safe token is generated.",
    )
    parser.add_argument(
        "--grant-accessor-service-account",
        help="Optional service account email to grant roles/secretmanager.secretAccessor.",
    )
    parser.add_argument(
        "--print-token",
        action="store_true",
        help="Print the token after storing it. Use only in a safe local terminal.",
    )
    parser.add_argument(
        "--gcloud",
        help="Optional path to gcloud/gcloud.cmd when it is not discoverable on PATH.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    gcloud = resolve_gcloud(args.gcloud)
    token = args.token or secrets.token_urlsafe(64)

    ensure_secret(args.project, args.secret_id, gcloud)
    add_secret_version(args.project, args.secret_id, token, gcloud)
    if args.grant_accessor_service_account:
        grant_accessor(args.project, args.secret_id, args.grant_accessor_service_account, gcloud)

    print(f"Secret {args.secret_id!r} updated in project {args.project!r}.")
    if args.print_token:
        print("Bearer token value. Store/share it through an approved secret channel:")
        print(token)
    else:
        print(
            "Token value was not printed. Re-run with --print-token only if you need to copy a newly generated token safely."
        )


if __name__ == "__main__":
    main()
