#!/usr/bin/env python3
"""truthfulness-agent CLI client — the way you talk to the DEPLOYED system.

Sends a request to the orchestrator via the shared A2A Agents Gateway.
This does NOT start any local server — for local dev see `make dev`; for
deployment see `make deploy-all`.

Required:

    --prompt <text>      What to ask the agent — always required, because agents
                         are instructed via natural language. E.g.
                         `--prompt "please classify and explain each statement"`.

Optional data source (pick at most one — the prompt alone is fine for
inline questions like "Classify: The Earth is flat."):

    --file <path>        Upload a local file to GCS + inject the URI into
                         the prompt so the agent's tools can read it. Two-step
                         under the hood (gcloud storage cp + JSON-RPC), hidden
                         behind this one command.

    --uri  <gs://…>      Same as --file but the file is already in GCS —
                         skips the upload.

Options:

    --agent <name>       Routing hint for the orchestrator (default: none —
                         orchestrator decides). One of: zero_shot, fine_tuned,
                         explainer. Only steers the orchestrator's prompt; the
                         orchestrator's LLM makes the final routing decision.

    --raw                Print the full JSON-RPC response (for debugging).
                         Without this, only the human-readable verdict text
                         is printed.

Env vars (from .env — populated by `make bootstrap` + `make deploy-all` +
`make register-orchestrator-gateway`):

    A2A_GATEWAY_BASE_URL                                 required
    A2A_GATEWAY_AGENT_ID                                 required
    A2A_GATEWAY_TRUTHFULNESS_ORCHESTRATOR_BEARER_TOKEN   required
    A2A_CALLER_EMAIL                                     required (gateway rejects without X-A2A-Caller)
    GCS_BUCKET                                           required for --file mode

Examples:

    # Inline question, no file
    python main.py --prompt "Classify: The Earth is flat."

    # Classify a local file — auto-uploads to GCS, URI appended to prompt
    python main.py --prompt "please classify and explain each statement" \
                   --file data/sample_1.json

    # Same but the file is already in GCS
    python main.py --prompt "please classify each statement" \
                   --uri gs://truthfulness-sft-europe-west1/uploads/mine.json

    # Steer routing to a specific sub-agent
    python main.py --prompt "use the fine-tuned model on this batch" \
                   --file data/sample_3.json --agent fine_tuned

Or via the Makefile (loads .env automatically):

    make ask PROMPT="Classify: The Earth is flat."
    make ask PROMPT="please classify and explain" FILE=data/sample_1.json
    make ask PROMPT="please classify" URI=gs://truthfulness-sft-europe-west1/uploads/mine.json
    make ask PROMPT="use fine-tuned" FILE=data/sample_3.json AGENT=fine_tuned

Cold-start note: first call after a quiet period can take 60-120s because the
gateway + orchestrator + sub-agents all scale from 0 in europe-west1.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import urllib.error
import urllib.request
import uuid
from pathlib import Path

TIMEOUT = 180  # seconds — accommodate cold starts across the whole chain


def _require_env(name: str) -> str:
    v = os.environ.get(name)
    if not v:
        sys.exit(
            f"❌ Missing env var: {name}\n"
            f"   Populate .env via `make bootstrap && make deploy-all && make register-orchestrator-gateway`."
        )
    return v


def _upload_file_to_gcs(local_path: Path, bucket: str) -> str:
    """Upload `local_path` to gs://<bucket>/uploads/<uuid>.<ext>. Returns URI."""
    if not local_path.exists():
        sys.exit(f"❌ File not found: {local_path}")
    suffix = local_path.suffix or ""
    remote = f"uploads/{uuid.uuid4()}{suffix}"
    uri = f"gs://{bucket}/{remote}"
    print(f"▶ Uploading {local_path} → {uri}", file=sys.stderr)
    result = subprocess.run(
        ["gcloud", "storage", "cp", str(local_path), uri],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        sys.exit(
            f"❌ Upload failed:\n{result.stderr}\n"
            f"   Does the bucket exist and does your SA have write access?\n"
            f"   Try: `make bootstrap-bucket`"
        )
    return uri


def _build_prompt(prompt: str, uri: str | None, agent_hint: str | None) -> str:
    """Compose the text the orchestrator's LLM will see. `prompt` is required."""
    parts = [prompt]
    if uri:
        parts.append(f"\n\nThe input file is available at the GCS URI: {uri}")
    if agent_hint:
        parts.append(f"\n\nRouting hint: use the {agent_hint} sub-agent.")
    return "".join(parts)


def _post_jsonrpc(base_url: str, agent_id: str, token: str, caller: str, text: str) -> dict:
    """POST an A2A message/send JSON-RPC request to the gateway. Returns parsed JSON."""
    request_id = str(uuid.uuid4())
    body = json.dumps({
        "jsonrpc": "2.0", "id": request_id, "method": "message/send",
        "params": {"message": {
            "role": "user", "messageId": request_id,
            "parts": [{"kind": "text", "text": text}],
        }},
    }).encode()
    url = f"{base_url.rstrip('/')}/agents/{agent_id}/"
    req = urllib.request.Request(
        url, method="POST", data=body,
        headers={
            "Authorization": f"Bearer {token}",
            "X-A2A-Caller": caller,
            "Content-Type": "application/json",
        },
    )
    print(f"▶ POST {url}", file=sys.stderr)
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
            payload = r.read()
    except urllib.error.HTTPError as e:
        payload = e.read()
        sys.exit(
            f"❌ Gateway returned HTTP {e.code}:\n{payload.decode(errors='replace')}"
        )
    return json.loads(payload)


def _extract_text(response: dict) -> str:
    """Pull the human-readable verdict text out of the JSON-RPC artifacts."""
    result = response.get("result", {}) or {}
    for artifact in result.get("artifacts", []) or []:
        for part in artifact.get("parts", []) or []:
            if part.get("kind") == "text":
                # The LAST text part in the last artifact is the final answer.
                pass
    # Simpler: last text part across all artifacts.
    texts = [
        part["text"]
        for artifact in result.get("artifacts", []) or []
        for part in artifact.get("parts", []) or []
        if part.get("kind") == "text"
    ]
    if not texts:
        return "(no text output — response had only data parts; use --raw to inspect)"
    return "\n\n".join(texts)


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--prompt", type=str, required=True,
                        help="Required. What to ask the agent, e.g. 'please classify and explain'.")
    data_source = parser.add_mutually_exclusive_group()
    data_source.add_argument("--file", type=Path,
                             help="Local file to upload to GCS; the URI is appended to the prompt.")
    data_source.add_argument("--uri", type=str,
                             help="GCS URI (gs://...) of a file already uploaded; appended to the prompt.")
    parser.add_argument("--agent", choices=["zero_shot", "fine_tuned", "explainer"],
                        default=None, help="Routing hint for the orchestrator.")
    parser.add_argument("--raw", action="store_true",
                        help="Print the full JSON-RPC response instead of just the verdict text.")
    args = parser.parse_args()

    # Auth + gateway config (required).
    base_url = _require_env("A2A_GATEWAY_BASE_URL")
    agent_id = _require_env("A2A_GATEWAY_AGENT_ID")
    token = _require_env("A2A_GATEWAY_TRUTHFULNESS_ORCHESTRATOR_BEARER_TOKEN")
    caller = _require_env("A2A_CALLER_EMAIL")

    # Determine the GCS URI (upload if --file, use as-is if --uri, none if --prompt).
    uri: str | None = None
    if args.file:
        bucket = _require_env("GCS_BUCKET")
        uri = _upload_file_to_gcs(args.file, bucket)
    elif args.uri:
        if not args.uri.startswith("gs://"):
            sys.exit(f"❌ --uri must start with gs:// — got: {args.uri}")
        uri = args.uri

    text = _build_prompt(args.prompt, uri, args.agent)
    response = _post_jsonrpc(base_url, agent_id, token, caller, text)

    if args.raw:
        print(json.dumps(response, indent=2))
    else:
        print(_extract_text(response))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())