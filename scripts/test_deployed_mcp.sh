#!/usr/bin/env bash
# Smoke-test the deployed MCP server on Cloud Run with one JSON-RPC call per tool.
#
# Reads MCP_SERVER_URL from .env, fetches a fresh Google identity token via
# gcloud, and exercises:
#   1. tools/list                  — sanity (server reachable + 4 tools registered)
#   2. predict_truthfulness        — zero-shot path with labels (returns metrics)
#   3. predict_truthfulness        — fine-tuned path with labels (returns metrics)
#   4. explain_truthfulness        — one statement (returns prediction + explanation)
#   5. check_finetune_status       — polls the seeded SFT job
#
# Deliberately does NOT call fine_tune_truthfulness — submitting a new SFT
# job costs real money and takes 30-90 minutes.
#
# Invoked by `make test-deployed-mcp`.

set -euo pipefail

ENV_FILE="${ENV_FILE:-.env}"
[ -f "$ENV_FILE" ] || { echo "❌ $ENV_FILE not found"; exit 1; }

URL=$(grep '^UNIFIED_APP_URL=' "$ENV_FILE" | cut -d= -f2- | tr -d '\n')
if [ -n "$URL" ]; then
  # Suffix with /mcp/ as the unified app mounts the MCP server under /mcp
  URL="${URL}/mcp/"
else
  URL=$(grep '^MCP_SERVER_URL=' "$ENV_FILE" | cut -d= -f2- | tr -d '\n')
fi

if [ -z "$URL" ]; then
  echo "❌ UNIFIED_APP_URL not set in $ENV_FILE — run \`make deploy-unified\` first"
  exit 1
fi

TOKEN=$(gcloud auth print-identity-token 2>/dev/null)
if [ -z "$TOKEN" ]; then
  echo "❌ gcloud auth print-identity-token returned empty — run \`gcloud auth login\`"
  exit 1
fi

echo "▶ MCP: $URL"
echo "▶ Token: ${#TOKEN} chars"
echo

call_tool() {
  # $1 = jsonrpc id, $2 = tool name, $3 = arguments JSON
  local id="$1" name="$2" args="$3"
  curl -sS -X POST "$URL" \
    -H "Authorization: Bearer $TOKEN" \
    -H "Content-Type: application/json" \
    -H "Accept: application/json, text/event-stream" \
    -d "{\"jsonrpc\":\"2.0\",\"id\":$id,\"method\":\"tools/call\",\"params\":{\"name\":\"$name\",\"arguments\":$args}}" \
    | sed -n 's/^data: //p' \
    | jq -r '.result.content[0].text // .error'
}

echo "── 1. tools/list ──────────────────────────────────────────"
curl -sS -X POST "$URL" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/list"}' \
  | sed -n 's/^data: //p' \
  | jq -r '.result.tools[].name'

echo
echo "── 2. predict_truthfulness  (zero-shot, with labels) ──────"
call_tool 2 predict_truthfulness \
  '{"points":[{"statement":"The Earth orbits the Sun."},{"statement":"The Great Wall is visible from space with the naked eye."}],"labels":[true,false]}'

echo
echo "── 3. predict_truthfulness  (fine-tuned, with labels) ─────"
call_tool 3 predict_truthfulness \
  '{"points":[{"statement":"The Earth orbits the Sun."},{"statement":"The Great Wall is visible from space with the naked eye."}],"use_fine_tuned":true,"labels":[true,false]}'

echo
echo "── 4. explain_truthfulness  (one statement) ──────────────"
call_tool 4 explain_truthfulness \
  '{"points":[{"statement":"The Earth orbits the Sun."}]}'

echo
echo "── 5. check_finetune_status ──────────────────────────────"
call_tool 5 check_finetune_status '{}'

echo
echo "✅ All 5 calls returned (look above for any error payloads)."
