#!/usr/bin/env bash
# MCP explain_truthfulness — returns prediction + natural-language reasoning per point.
set -euo pipefail
source "$(dirname "$0")/_common.sh"

curl -sS -X POST "$URL/mcp/" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  -d '{
    "jsonrpc":"2.0","id":4,"method":"tools/call",
    "params":{
      "name":"explain_truthfulness",
      "arguments":{
        "points":[{"statement":"The Earth orbits the Sun."}]
      }
    }
  }' \
  | sed -n 's/^data: //p' | jq '.result.content[0].text'
