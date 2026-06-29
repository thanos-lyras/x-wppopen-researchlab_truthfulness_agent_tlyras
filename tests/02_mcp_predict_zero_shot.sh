#!/usr/bin/env bash
# MCP predict_truthfulness — zero-shot path, with ground-truth labels.
# When labels are provided, the response includes a `metrics` block
# (accuracy / precision / recall / f1 / confusion matrix).
set -euo pipefail
source "$(dirname "$0")/_common.sh"

curl -sS -X POST "$URL/mcp/" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  -d '{
    "jsonrpc":"2.0","id":2,"method":"tools/call",
    "params":{
      "name":"predict_truthfulness",
      "arguments":{
        "points":[
          {"statement":"The Earth orbits the Sun."},
          {"statement":"The Great Wall is visible from the moon with the naked eye."}
        ],
        "labels":[true,false]
      }
    }
  }' \
  | sed -n 's/^data: //p' | jq '.result.content[0].text'
