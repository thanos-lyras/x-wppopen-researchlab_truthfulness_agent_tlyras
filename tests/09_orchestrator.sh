#!/usr/bin/env bash
# A2A: send a request to the orchestrator. It decides which sub-agent to
# delegate to via `transfer_to_agent`. Note: with `message/send` the response
# only carries the routing decision — the sub-agent's final answer doesn't
# stream back in the same call (orchestrator card has no streaming capability).
# Hit the sub-agent directly (06–08) for the actual classification result.
set -euo pipefail
source "$(dirname "$0")/_common.sh"

curl -sS -X POST "$URL/" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "jsonrpc":"2.0","id":1,"method":"message/send",
    "params":{
      "message":{
        "role":"user",
        "parts":[{"kind":"text","text":"Classify: \"The Earth orbits the Sun.\""}],
        "messageId":"orch-1"
      }
    }
  }' \
  | jq '{transfer_to: .result.metadata.adk_actions.transferToAgent, artifacts: .result.artifacts}'
