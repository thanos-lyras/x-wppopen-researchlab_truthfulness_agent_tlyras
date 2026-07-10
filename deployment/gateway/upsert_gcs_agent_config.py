#!/usr/bin/env python
"""Create or update one per-agent gateway JSON config object in GCS.

This helper stores non-sensitive gateway agent config only. Bearer token values
belong in Secret Manager; by default the gateway resolves the conventional token
secret named ``a2a-gateway-{agent-id}-bearer-token``.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

from google.cloud import storage

AGENT_ID_RE = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9_.-]{0,62}$")
SENSITIVE_FIELDS = {
    "bearer_tokens",
    "bearer_token_env_var",
    "bearer_token_secret_id",
    "bearer_token_secret_resource",
}


def _load_json_file(path: Path) -> dict[str, Any]:
    try:
        loaded = json.loads(path.read_text(encoding="utf-8-sig"))
    except json.JSONDecodeError as exc:
        raise SystemExit(f"{path} does not contain valid JSON: {exc}") from exc
    if isinstance(loaded, dict) and isinstance(loaded.get("agents"), list):
        agents = loaded["agents"]
        if len(agents) != 1 or not isinstance(agents[0], dict):
            raise SystemExit("--config may contain a single agent object or {'agents': [single_agent]} only.")
        return dict(agents[0])
    if not isinstance(loaded, dict):
        raise SystemExit("--config must contain one JSON object.")
    return dict(loaded)


def _strip_sensitive_fields(data: dict[str, Any], *, allow_secret_refs: bool) -> dict[str, Any]:
    clean = dict(data)
    clean.pop("bearer_tokens", None)
    if not allow_secret_refs:
        for field in SENSITIVE_FIELDS - {"bearer_tokens"}:
            clean.pop(field, None)
    return clean


def _parse_card_overrides(raw: str) -> dict[str, Any]:
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise SystemExit(f"--card-overrides must be valid JSON: {exc}") from exc
    if not isinstance(parsed, dict):
        raise SystemExit("--card-overrides must be a JSON object.")
    return parsed


def _build_config(args: argparse.Namespace) -> dict[str, Any]:
    if args.config:
        data = _load_json_file(args.config)
    else:
        data = {}
    updates = {
        "id": args.agent_id,
        "backend_kind": args.backend_kind,
        "upstream_base_url": args.upstream_base_url,
        "vertex_agent_engine_resource_name": args.vertex_agent_engine_resource_name,
        "vertex_agent_engine_query_class_method": args.vertex_agent_engine_query_class_method,
        "name": args.name,
        "description": args.description,
        "monthly_budget_usd": args.monthly_budget_usd,
        "estimated_cost_per_call_usd": args.estimated_cost_per_call_usd,
        "capture_call_content": args.capture_call_content,
        "capture_call_content_max_chars": args.capture_call_content_max_chars,
        "public_base_url": args.public_base_url,
        "card_path": args.card_path,
        "expose_full_agent_card": args.expose_full_agent_card,
        "forward_id_token": args.forward_id_token,
    }
    for key, value in updates.items():
        if value is not None:
            data[key] = value
    if args.card_overrides is not None:
        data["card_overrides"] = _parse_card_overrides(args.card_overrides)
    return _strip_sensitive_fields(data, allow_secret_refs=args.allow_secret_refs)


def _validate_config(data: dict[str, Any]) -> None:
    agent_id = str(data.get("id") or "")
    if not AGENT_ID_RE.match(agent_id):
        raise SystemExit("Agent id is required and must match ^[a-zA-Z0-9][a-zA-Z0-9_.-]{0,62}$.")
    backend_kind = str(data.get("backend_kind") or "http_jsonrpc")
    if backend_kind not in ("http_jsonrpc", "vertex_agent_runtime"):
        raise SystemExit("backend_kind must be 'http_jsonrpc' or 'vertex_agent_runtime'.")
    if backend_kind == "vertex_agent_runtime":
        if not str(data.get("vertex_agent_engine_resource_name") or "").strip():
            raise SystemExit(
                "vertex_agent_engine_resource_name is required when backend_kind is vertex_agent_runtime "
                "(e.g. projects/PROJECT/locations/REGION/reasoningEngines/ID)."
            )
    elif not str(data.get("upstream_base_url") or "").startswith(("http://", "https://")):
        raise SystemExit(
            "upstream_base_url is required and must start with http:// or https:// for backend_kind http_jsonrpc."
        )
    if float(data.get("monthly_budget_usd", 0)) <= 0:
        raise SystemExit("monthly_budget_usd is required and must be greater than zero.")
    max_chars = int(data.get("capture_call_content_max_chars", 4000))
    if max_chars < 0 or max_chars > 20000:
        raise SystemExit("capture_call_content_max_chars must be between 0 and 20000.")
    if "bearer_tokens" in data:
        raise SystemExit("Do not store bearer_tokens in GCS config. Use Secret Manager for token values.")


def _object_name(prefix: str, agent_id: str) -> str:
    clean_prefix = prefix.strip().strip("/")
    return f"{clean_prefix}/{agent_id}.json" if clean_prefix else f"{agent_id}.json"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", help="Optional Google Cloud project for the Storage client.")
    parser.add_argument("--bucket", required=True, help="GCS bucket containing gateway agent config JSON objects.")
    parser.add_argument("--prefix", default="agents", help="GCS prefix/folder. Default: agents")
    parser.add_argument("--config", type=Path, help="Optional source JSON file. CLI flags override this file.")
    parser.add_argument("--agent-id", help="Gateway public agent id, e.g. data-science-qa.")
    parser.add_argument(
        "--backend-kind",
        choices=["http_jsonrpc", "vertex_agent_runtime"],
        help="Backend kind. Gateway defaults to http_jsonrpc. Use vertex_agent_runtime for Vertex AI Agent Engine.",
    )
    parser.add_argument("--upstream-base-url", help="Upstream A2A service base URL (required for http_jsonrpc).")
    parser.add_argument(
        "--vertex-agent-engine-resource-name",
        help="Vertex Agent Engine resource name (required for vertex_agent_runtime): "
        "projects/PROJECT/locations/REGION/reasoningEngines/ID.",
    )
    parser.add_argument(
        "--vertex-agent-engine-query-class-method",
        help="Vertex runtime class method. Gateway defaults to on_message_send.",
    )
    parser.add_argument(
        "--card-overrides",
        help='JSON object merged into the public card, e.g. \'{"preferredTransport":"JSONRPC"}\'.',
    )
    parser.add_argument("--name", help="Public display name.")
    parser.add_argument("--description", help="Public description.")
    parser.add_argument("--monthly-budget-usd", type=float, help="Required monthly budget in USD.")
    parser.add_argument("--estimated-cost-per-call-usd", type=float, help="Estimated cost per authenticated call. Defaulted by gateway if omitted.")
    parser.add_argument("--capture-call-content", action=argparse.BooleanOptionalAction, default=None, help="Store JSON-RPC request content in usage events.")
    parser.add_argument("--capture-call-content-max-chars", type=int, help="Maximum captured request-content characters, 0..20000.")
    parser.add_argument("--public-base-url", help="Optional explicit public base URL. Usually omit.")
    parser.add_argument("--card-path", help="Optional upstream agent-card path. Defaults in gateway to /.well-known/agent-card.json.")
    parser.add_argument("--expose-full-agent-card", action=argparse.BooleanOptionalAction, default=None, help="Expose full upstream card instead of sanitized card.")
    parser.add_argument("--forward-id-token", action=argparse.BooleanOptionalAction, default=None, help="Have the gateway mint a Google ID token for the upstream Cloud Run service (required when the upstream is --no-allow-unauthenticated).")
    parser.add_argument("--allow-secret-refs", action="store_true", help="Keep bearer_token_secret_* reference fields from --config. Never keeps bearer_tokens values.")
    parser.add_argument("--dry-run", action="store_true", help="Print resulting JSON without uploading.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    data = _build_config(args)
    _validate_config(data)
    rendered = json.dumps(data, indent=2, sort_keys=True) + "\n"
    object_name = _object_name(args.prefix, str(data["id"]))
    if args.dry_run:
        print(rendered, end="")
        print(f"Dry run only; would upload gs://{args.bucket}/{object_name}", file=sys.stderr)
        return 0
    client = storage.Client(project=args.project)
    blob = client.bucket(args.bucket).blob(object_name)
    blob.upload_from_string(rendered, content_type="application/json")
    print(f"Uploaded gs://{args.bucket}/{object_name}")
    print("Bearer token values are not stored in this config. Ensure the token secret exists and the gateway service account can access it.")
    print("The gateway picks this up after A2A_GATEWAY_CONFIG_CACHE_SECONDS or immediately after /monitoring rescan.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


