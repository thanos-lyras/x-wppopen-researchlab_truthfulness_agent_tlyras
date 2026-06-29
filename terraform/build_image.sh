#!/usr/bin/env bash
# Thin wrapper: cd to repo root, hand off to terraform/build_image.py.
# Invoked by terraform/main.tf via null_resource.build_image's local-exec.
set -euo pipefail
cd "$(dirname "$0")/.."
exec uv run python terraform/build_image.py "$@"
