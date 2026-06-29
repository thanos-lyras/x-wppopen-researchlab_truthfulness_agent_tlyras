#!/usr/bin/env bash
# Sanity: list every MCP tool the deployed server exposes.
set -euo pipefail
source "$(dirname "$0")/_common.sh"

curl -sS -X POST "$URL/mcp/" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/list"}' \
  | sed -n 's/^data: //p' | jq '.result.tools[].name'
