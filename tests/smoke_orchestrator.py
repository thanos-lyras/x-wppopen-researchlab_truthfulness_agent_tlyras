#!/usr/bin/env python3
"""End-to-end smoke test for the orchestrator via the A2A Agents Gateway.

Reads gateway URL + agent id + bearer token from env, then:
  1. GET /health              — asserts the agent id appears in agents[]
  2. GET /agents/<id>/.well-known/agent-card.json — asserts 200
  3. POST /agents/<id>/       — sends a canned JSON-RPC message/send and prints the response

Env vars (read from `.env` when invoked via `make smoke-orchestrator-gateway`):
  A2A_GATEWAY_BASE_URL                                     required
  A2A_GATEWAY_AGENT_ID                                     required
  A2A_GATEWAY_TRUTHFULNESS_ORCHESTRATOR_BEARER_TOKEN       required
  A2A_CALLER_EMAIL                                         required (gateway rejects without X-A2A-Caller)

Cold-start note: the first call after a quiet period can take 60-120s because the
gateway + orchestrator + all three sub-agents (all in europe-west1) scale from 0.
Timeouts here are generous accordingly.
"""

from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request
import uuid

TIMEOUT = 180  # seconds — accommodate cold starts across the whole chain


def _req(method: str, url: str, headers: dict[str, str], body: bytes | None = None) -> tuple[int, bytes]:
    req = urllib.request.Request(url, method=method, headers=headers, data=body)
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
            return r.status, r.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read()


def _env(name: str) -> str:
    v = os.environ.get(name)
    if not v:
        sys.exit(f"❌ Missing env var: {name}")
    return v


def main() -> int:
    base = _env("A2A_GATEWAY_BASE_URL").rstrip("/")
    agent_id = _env("A2A_GATEWAY_AGENT_ID")
    token = _env("A2A_GATEWAY_TRUTHFULNESS_ORCHESTRATOR_BEARER_TOKEN")
    caller = _env("A2A_CALLER_EMAIL")

    auth = {"Authorization": f"Bearer {token}", "X-A2A-Caller": caller}

    # 1. Gateway health — agent must be registered.
    print(f"▶ GET {base}/health")
    status, payload = _req("GET", f"{base}/health", headers={})
    print(f"  → {status}")
    if status != 200:
        print(payload.decode(errors="replace"))
        return 1
    health = json.loads(payload)
    # The gateway's /health payload may express agents as either a list of
    # `{id: ...}` objects or a bare list of id strings — accept both.
    agent_ids = [a.get("id") if isinstance(a, dict) else a for a in health.get("agents", [])]
    if agent_id not in agent_ids:
        sys.exit(f"❌ Agent {agent_id!r} not in gateway's agents[]: {agent_ids}")
    print(f"  ✅ {agent_id!r} registered")

    # 2. Agent card via gateway — proves auth + upstream reachability.
    card_url = f"{base}/agents/{agent_id}/.well-known/agent-card.json"
    print(f"\n▶ GET {card_url}")
    status, payload = _req("GET", card_url, headers=auth)
    print(f"  → {status}")
    if status != 200:
        print(payload.decode(errors="replace"))
        return 1
    card = json.loads(payload)
    print(f"  ✅ card: name={card.get('name')!r} version={card.get('version')!r}")

    # 3. JSON-RPC message/send with a canned truthfulness statement.
    rpc_url = f"{base}/agents/{agent_id}/"
    request_id = str(uuid.uuid4())
    body = json.dumps({
        "jsonrpc": "2.0",
        "id": request_id,
        "method": "message/send",
        "params": {
            "message": {
                "role": "user",
                "parts": [{
                    "kind": "text",
                    "text": (
                        "Classify this statement as truthful or untruthful "
                        "and explain your reasoning: "
                        "'The Earth is flat.'"
                    ),
                }],
                "messageId": request_id,
            },
        },
    }).encode()
    print(f"\n▶ POST {rpc_url}")
    status, payload = _req(
        "POST", rpc_url,
        headers={**auth, "Content-Type": "application/json"},
        body=body,
    )
    print(f"  → {status}")
    text = payload.decode(errors="replace")
    if status != 200:
        print(text)
        return 1
    print("  ✅ 200 OK — response body:")
    try:
        print(json.dumps(json.loads(text), indent=2)[:4000])
    except json.JSONDecodeError:
        print(text[:4000])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
