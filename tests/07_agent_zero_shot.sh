#!/usr/bin/env bash
# A2A: send a classification request to the zero_shot predictor sub-agent.
# The agent calls MCP predict_truthfulness with use_fine_tuned=false (default).
set -euo pipefail
source "$(dirname "$0")/_common.sh"

curl -sS -X POST "$URL/zero_shot/" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "jsonrpc":"2.0","id":1,"method":"message/send",
    "params":{
      "message":{
        "role":"user",
        "parts":[{"kind":"text","text":"Classify: \"The Earth orbits the Sun.\""}],
        "messageId":"zero-shot-1"
      }
    }
  }' \
  | jq -r '.result.artifacts[].parts[].text // .'
