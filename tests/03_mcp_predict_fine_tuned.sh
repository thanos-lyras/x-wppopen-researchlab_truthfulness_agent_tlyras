#!/usr/bin/env bash
# MCP predict_truthfulness — fine-tuned path (use_fine_tuned=true).
# Falls back to FINE_TUNED_BASE_MODEL when FINE_TUNED_MODEL is unset on the server.
set -euo pipefail
source "$(dirname "$0")/_common.sh"

curl -sS -X POST "$URL/mcp/" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  -d '{
    "jsonrpc":"2.0","id":3,"method":"tools/call",
    "params":{
      "name":"predict_truthfulness",
      "arguments":{
        "points":[{"statement":"The Earth orbits the Sun."}],
        "use_fine_tuned":true
      }
    }
  }' \
  | sed -n 's/^data: //p' | jq '.result.content[0].text'
