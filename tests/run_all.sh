#!/usr/bin/env bash
# Run every other script in this folder in numeric order, printing a header per test.
# Auth + URL resolve once and propagate via env to children so we don't gcloud-token
# 9 times.
set -euo pipefail
cd "$(dirname "$0")"

export URL="${URL:-https://truthfulness-unified-fq5fpdmt7a-uc.a.run.app}"
export TOKEN="${TOKEN:-$(gcloud auth print-identity-token)}"

for script in [0-9][0-9]_*.sh; do
  echo "════════════════════════════════════════════════════════════"
  echo "  $script"
  echo "════════════════════════════════════════════════════════════"
  bash "$script" || echo "❌ $script failed (continuing)"
  echo
done
