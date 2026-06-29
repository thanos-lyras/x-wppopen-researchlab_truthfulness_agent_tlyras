#!/usr/bin/env bash
# A2A: send a classify+reason request to the explainer sub-agent.
# The agent calls MCP explain_truthfulness, which returns prediction + reasoning.
set -euo pipefail
source "$(dirname "$0")/_common.sh"

curl -sS -X POST "$URL/explainer/" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "jsonrpc":"2.0","id":1,"method":"message/send",
    "params":{
      "message":{
        "role":"user",
        "parts":[{"kind":"text","text":"Explain why: \"The Earth orbits the Sun.\""}],
        "messageId":"explainer-1"
      }
    }
  }' \
  | jq -r '.result.artifacts[].parts[].text // .'
