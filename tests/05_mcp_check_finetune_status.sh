#!/usr/bin/env bash
# MCP check_finetune_status — poll the latest SFT job from LAST_TUNING_JOB.
# Returns 'no_job' until a fine_tune_truthfulness call has been made.
set -euo pipefail
source "$(dirname "$0")/_common.sh"

curl -sS -X POST "$URL/mcp/" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  -d '{"jsonrpc":"2.0","id":5,"method":"tools/call","params":{"name":"check_finetune_status","arguments":{}}}' \
  | sed -n 's/^data: //p' | jq '.result.content[0].text'
