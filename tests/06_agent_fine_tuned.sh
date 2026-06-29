#!/usr/bin/env bash
# A2A: send a classification request to the fine_tuned predictor sub-agent.
# The agent calls the MCP predict_truthfulness tool with use_fine_tuned=true.
set -euo pipefail
source "$(dirname "$0")/_common.sh"

curl -sS -X POST "$URL/fine_tuned/" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "jsonrpc":"2.0","id":1,"method":"message/send",
    "params":{
      "message":{
        "role":"user",
        "parts":[{"kind":"text","text":"Classify: 1) \"The Earth orbits the Sun.\" 2) \"The Great Wall is visible from the moon with the naked eye.\""}],
        "messageId":"fine-tuned-1"
      }
    }
  }' \
  | jq -r '.result.artifacts[].parts[].text // .'
