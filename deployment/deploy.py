#!/usr/bin/env python3
"""Deploy the truthfulness-agent Cloud Run services and register with the A2A Gateway.

Two families of subcommands:

    Service deploys (idempotent, safe to re-run):
        python deployment/deploy.py mcp
        python deployment/deploy.py zero-shot
        python deployment/deploy.py fine-tuned
        python deployment/deploy.py explainer
        python deployment/deploy.py orchestrator
        python deployment/deploy.py all           # all five in dependency order

    Gateway wiring (one-shot / occasional):
        python deployment/deploy.py register-gateway        # mints bearer + uploads gateway config
        python deployment/deploy.py update-gateway-config   # re-uploads config without rotating token
        python deployment/deploy.py smoke-gateway           # end-to-end smoke via the gateway

Or via the Makefile wrappers:
    make deploy-mcp   /   make deploy-all   /
    make register-orchestrator-gateway   /
    make update-orchestrator-gateway-config   /
    make smoke-orchestrator-gateway

Dependency order for `all`:
    1. truthfulness-mcp          (sub-agents read MCP_SERVER_URL)
    2. truthfulness-zero-shot
    3. truthfulness-fine-tuned
    4. truthfulness-explainer
    5. truthfulness-orchestrator (reads the three sub-agents' *_A2A_URL)

Each service deploy writes its URL back to `.env`, so later steps in this
sequence pick up the URLs the earlier steps just produced. Gateway subcommands
are NOT included in `all` — running them there would rotate the bearer token
every deploy and break existing callers.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

from dotenv import dotenv_values, set_key

from deployment import bootstrap_bucket

REPO_ROOT = Path(__file__).resolve().parent.parent
ENV_FILE = REPO_ROOT / ".env"
REPO = "cloud-run-source-deploy"

# Order matters when deploying "all":
DEPLOY_ORDER = ["mcp", "zero-shot", "fine-tuned", "explainer", "orchestrator"]

# A2A Agents Gateway service account — granted roles/run.invoker on the
# orchestrator so the gateway (which mints an ID token per upstream call)
# can reach the --no-allow-unauthenticated orchestrator.
GATEWAY_SERVICE_ACCOUNT = (
    "a2a-agent-gateway@x-wppai-dataspine-choreo-dev.iam.gserviceaccount.com"
)

# Gateway registration constants (mirror the Makefile targets).
GATEWAY_SECRET_ID = "a2a-gateway-truthfulness-orchestrator-bearer-token"
GATEWAY_AGENT_ID = "truthfulness-orchestrator"
GATEWAY_DESC = (
    "ADK 2.0 orchestrator classifying statements as truthful/untruthful via "
    "zero-shot, fine-tuned, and explainer sub-agents."
)


# ── tiny shell helpers ─────────────────────────────────────────────────

def _env() -> dict[str, str]:
    """Read `.env` as a dict; treat missing keys as empty strings."""
    return {k: (v or "") for k, v in dotenv_values(ENV_FILE).items()}


def _image(project: str, location: str, service_name: str) -> str:
    return f"{location}-docker.pkg.dev/{project}/{REPO}/{service_name}:latest"


def _project_number(project: str) -> str:
    """Fetch GCP project number — used to predict Cloud Run public URLs."""
    return _run_capture(
        ["gcloud", "projects", "describe", project, "--format=value(projectNumber)"]
    ).strip()


def _run_capture(cmd: list[str]) -> str:
    """Run a subprocess, capture stdout, stream stderr to terminal."""
    result = subprocess.run(cmd, check=True, stdout=subprocess.PIPE, text=True)
    return result.stdout


def _run_stream(cmd: list[str]) -> None:
    """Run a subprocess; stream both streams to terminal; raise on failure."""
    subprocess.run(cmd, cwd=REPO_ROOT, check=True)


def _ensure_repo(project: str, location: str) -> None:
    print(f"▶ Ensuring Artifact Registry repo '{REPO}' exists in {location}...")
    probe = subprocess.run(
        ["gcloud", "artifacts", "repositories", "describe", REPO,
         f"--location={location}", f"--project={project}"],
        capture_output=True,
    )
    if probe.returncode == 0:
        return
    _run_stream([
        "gcloud", "artifacts", "repositories", "create", REPO,
        "--repository-format=docker",
        f"--location={location}", f"--project={project}",
    ])


def _build_image(project: str, image: str, cloudbuild_path: str) -> None:
    print(f"▶ Building {image} via Cloud Build ({cloudbuild_path})...")
    _run_stream([
        "gcloud", "builds", "submit",
        f"--project={project}",
        "--config", cloudbuild_path,
        f"--substitutions=_IMAGE_TAG={image}",
        ".",
    ])


def _deploy_service(
    *, service_name: str, image: str, project: str, location: str,
    env_vars: dict[str, str],
    ingress: str = "all",
    allow_unauthenticated: bool = True,
    vpc_egress: str | None = None,
) -> str:
    """Deploy a Cloud Run service. Returns its public HTTPS URL.

    - `ingress`: "all" (default) or "internal" (only accepts traffic that
      arrives via a VPC network in the same project — requires callers to
      have `vpc_egress` set).
    - `allow_unauthenticated`: True adds --allow-unauthenticated (default);
      False adds --no-allow-unauthenticated (IAM-locked; caller must
      subsequently be granted `roles/run.invoker`).
    - `vpc_egress`: when set (e.g. "all-traffic"), routes the service's
      outbound HTTPS through the default VPC. Required on any service that
      CALLS a --ingress=internal destination in the same project. Requires
      Private Google Access enabled on the default subnet (one-time:
      `gcloud compute networks subnets update default --region=<r>
      --enable-private-ip-google-access`).
    """
    print(f"▶ Deploying {service_name} to Cloud Run in {location} "
          f"(ingress={ingress}, unauth={'allowed' if allow_unauthenticated else 'blocked'}, "
          f"vpc_egress={vpc_egress or 'off'})...")
    env_str = ",".join(f"{k}={v}" for k, v in env_vars.items())
    auth_flag = "--allow-unauthenticated" if allow_unauthenticated else "--no-allow-unauthenticated"
    cmd = [
        "gcloud", "run", "deploy", service_name,
        f"--image={image}",
        f"--region={location}",
        f"--project={project}",
        auth_flag,
        f"--ingress={ingress}",
        f"--set-env-vars={env_str}",
        "--format=value(status.url)",
    ]
    if vpc_egress is not None:
        cmd[-1:-1] = [
            "--network=default",
            "--subnet=default",
            f"--vpc-egress={vpc_egress}",
        ]
    url = _run_capture(cmd).strip()
    print(f"✅ Deployed: {url}")
    return url


def _grant_run_invoker(project: str, location: str, service_name: str, member: str) -> None:
    """Grant `roles/run.invoker` on a Cloud Run service to a principal.

    Idempotent — gcloud silently succeeds if the binding already exists.
    """
    print(f"▶ Granting roles/run.invoker on {service_name} to {member}...")
    _run_stream([
        "gcloud", "run", "services", "add-iam-policy-binding", service_name,
        f"--region={location}",
        f"--project={project}",
        f"--member={member}",
        "--role=roles/run.invoker",
    ])


def _write_env(key: str, value: str) -> None:
    set_key(str(ENV_FILE), key, value, quote_mode="never")
    print(f"✅ Wrote {key}={value} to .env")


def _gcp_env(env: dict[str, str]) -> dict[str, str]:
    """The GCP env vars every service needs."""
    return {
        "GOOGLE_CLOUD_PROJECT": env["GOOGLE_CLOUD_PROJECT"],
        "GOOGLE_CLOUD_LOCATION": env["GOOGLE_CLOUD_LOCATION"],
        "GOOGLE_GENAI_USE_VERTEXAI": "True",
    }


def _public_a2a_env(prefix: str, public_host: str) -> dict[str, str]:
    """`<PREFIX>_A2A_PUBLIC_HOST/PROTOCOL/PUBLIC_PORT` — makes `to_a2a()`
    advertise the public HTTPS URL in its agent card instead of localhost."""
    return {
        f"{prefix}_A2A_PUBLIC_HOST": public_host,
        f"{prefix}_A2A_PROTOCOL": "https",
        f"{prefix}_A2A_PUBLIC_PORT": "443",
    }


# ── per-service deploys ────────────────────────────────────────────────

def deploy_mcp() -> None:
    env = _env()
    project, location = env["GOOGLE_CLOUD_PROJECT"], env["GOOGLE_CLOUD_LOCATION"]
    image = _image(project, location, "truthfulness-mcp")

    _ensure_repo(project, location)
    _build_image(project, image, "mcp_server/cloudbuild.yaml")

    url = _deploy_service(
        service_name="truthfulness-mcp",
        image=image, project=project, location=location,
        # ingress=internal + vpc_egress: MCP is only reachable via the default
        # VPC. Every caller (orchestrator + 3 sub-agents) must have vpc_egress
        # set too. External laptops hit the ingress edge and get 404.
        ingress="internal",
        vpc_egress="all-traffic",
        env_vars={
            **_gcp_env(env),
            "ZERO_SHOT_MODEL": env.get("ZERO_SHOT_MODEL", ""),
            "EXPLAINER_MODEL": env.get("EXPLAINER_MODEL", ""),
            "GCS_BUCKET": env.get("GCS_BUCKET", ""),
            "FINE_TUNED_BASE_MODEL": env.get("FINE_TUNED_BASE_MODEL", ""),
            "FINE_TUNED_EPOCHS": env.get("FINE_TUNED_EPOCHS", ""),
            "FINE_TUNED_ADAPTER_SIZE": env.get("FINE_TUNED_ADAPTER_SIZE", ""),
            "FINE_TUNED_LRM": env.get("FINE_TUNED_LRM", ""),
            "FINE_TUNED_MODEL": env.get("FINE_TUNED_MODEL", ""),
            "LAST_TUNING_JOB": env.get("LAST_TUNING_JOB", ""),
        },
    )
    _write_env("MCP_SERVER_URL", f"{url}/mcp/")


def _deploy_subagent(name_kebab: str, *, extra_env: dict[str, str] | None = None) -> None:
    """Deploy a sub-agent (zero-shot / fine-tuned / explainer).

    All three follow the same shape: build → inject MCP_SERVER_URL + the
    *_A2A_PUBLIC_HOST trio + (optionally) a model env var → write *_A2A_URL.
    """
    env = _env()
    project, location = env["GOOGLE_CLOUD_PROJECT"], env["GOOGLE_CLOUD_LOCATION"]
    name_upper = name_kebab.upper().replace("-", "_")       # "zero-shot" → "ZERO_SHOT"
    name_snake = name_kebab.replace("-", "_")               # "zero-shot" → "zero_shot"
    service_name = f"truthfulness-{name_kebab}"
    image = _image(project, location, service_name)
    public_host = f"{service_name}-{_project_number(project)}.{location}.run.app"

    _ensure_repo(project, location)
    _build_image(project, image, f"agents/{name_snake}/cloudbuild.yaml")

    url = _deploy_service(
        service_name=service_name, image=image,
        project=project, location=location,
        # ingress=internal + vpc_egress: sub-agent is only reachable from
        # the orchestrator over the default VPC. Sub-agent also has vpc_egress
        # so it can reach the (also ingress=internal) MCP server. External
        # laptops get 404 at the edge.
        ingress="internal",
        vpc_egress="all-traffic",
        env_vars={
            **_gcp_env(env),
            "MCP_SERVER_URL": env.get("MCP_SERVER_URL", ""),
            **(extra_env or {}),
            **_public_a2a_env(name_upper, public_host),
        },
    )
    _write_env(f"{name_upper}_A2A_URL", f"{url}/.well-known/agent-card.json")


def deploy_zero_shot() -> None:
    _deploy_subagent("zero-shot", extra_env={"ZERO_SHOT_MODEL": _env().get("ZERO_SHOT_MODEL", "")})


def deploy_fine_tuned() -> None:
    # Fine-tuned agent's wrapping LLM uses FINE_TUNED_AGENT_MODEL (defaulted
    # in agent.py). The fine-tuning-specific vars (FINE_TUNED_BASE_MODEL,
    # LAST_TUNING_JOB, …) are consumed by the MCP server's predict tool,
    # NOT by this agent, so they're not injected here.
    _deploy_subagent("fine-tuned")


def deploy_explainer() -> None:
    _deploy_subagent("explainer", extra_env={"EXPLAINER_MODEL": _env().get("EXPLAINER_MODEL", "")})


def deploy_orchestrator() -> None:
    env = _env()
    project, location = env["GOOGLE_CLOUD_PROJECT"], env["GOOGLE_CLOUD_LOCATION"]
    service_name = "truthfulness-orchestrator"
    image = _image(project, location, service_name)
    public_host = f"{service_name}-{_project_number(project)}.{location}.run.app"

    _ensure_repo(project, location)
    _build_image(project, image, "agents/cloudbuild.yaml")

    url = _deploy_service(
        service_name=service_name, image=image,
        project=project, location=location,
        # Ingress stays "all" because the A2A Gateway lives in a different
        # project's edge context; its traffic isn't classified as internal
        # to our VPC. IAM (--no-allow-unauthenticated + gateway SA has
        # run.invoker) is what enforces auth here.
        ingress="all",
        allow_unauthenticated=False,
        # vpc_egress: orchestrator must route through our VPC on outbound
        # calls to (a) the ingress=internal sub-agents and (b) the
        # ingress=internal MCP (from its own direct McpToolset for the
        # /invoke flow). Vertex + GCS calls stay on Google's private
        # backbone via Private Google Access on the default subnet.
        vpc_egress="all-traffic",
        env_vars={
            **_gcp_env(env),
            "ORCHESTRATOR_MODEL": env.get("ORCHESTRATOR_MODEL", ""),
            "EXPLAINER_A2A_URL": env.get("EXPLAINER_A2A_URL", ""),
            "FINE_TUNED_A2A_URL": env.get("FINE_TUNED_A2A_URL", ""),
            "ZERO_SHOT_A2A_URL": env.get("ZERO_SHOT_A2A_URL", ""),
            # The /invoke REST handler uploads the request body to GCS via
            # GCSService(), which reads GCS_BUCKET + GCS_LOCATION from env.
            # The orchestrator also has direct McpToolset calls into MCP for
            # explain_truthfulness_from_gcs / predict_truthfulness_from_gcs,
            # which need MCP_SERVER_URL.
            "GCS_BUCKET": env.get("GCS_BUCKET", ""),
            "GCS_LOCATION": env.get("GCS_LOCATION", "europe-west1"),
            "MCP_SERVER_URL": env.get("MCP_SERVER_URL", ""),
            **_public_a2a_env("ORCHESTRATOR", public_host),
        },
    )
    # Grant the A2A Gateway SA invoker so it can call this locked-down service
    # with the ID token it mints per request (forward_id_token=true in the
    # gateway's GCS config). Idempotent — safe on every redeploy.
    _grant_run_invoker(
        project, location, service_name,
        member=f"serviceAccount:{GATEWAY_SERVICE_ACCOUNT}",
    )
    _write_env("ORCHESTRATOR_A2A_URL", f"{url}/.well-known/agent-card.json")


# ── A2A Gateway registration ───────────────────────────────────────────
# The gateway wiring is a separate concern from service deploys:
#   - `register-gateway` is one-shot per registration (mints a NEW bearer
#     token). Running it twice rotates the token — all existing callers must
#     be updated with the new value. Deliberately excluded from `all`.
#   - `update-gateway-config` is safe to re-run any time the orchestrator
#     URL changes (region migration, service rename). Never rotates the
#     token.
#   - `smoke-gateway` is a read-only end-to-end verification through the
#     gateway. Requires the four A2A_GATEWAY_* vars in .env.
#
# All three shell out to the standalone scripts under `deployment/gateway/`
# so the argument surface + gcloud path resolution lives in ONE place.

def _gateway_context() -> tuple[str, str, str]:
    """Return (project, upstream_base_url, config_bucket) from .env.

    Requires ORCHESTRATOR_A2A_URL — populated after `deploy_orchestrator()`
    has written it back to .env. Raises SystemExit with a clear message
    otherwise so the operator knows to run `deploy orchestrator` first.
    """
    env = _env()
    project = env.get("GOOGLE_CLOUD_PROJECT")
    if not project:
        raise SystemExit("❌ GOOGLE_CLOUD_PROJECT missing in .env")
    orchestrator_url = env.get("ORCHESTRATOR_A2A_URL", "")
    if not orchestrator_url:
        raise SystemExit(
            "❌ ORCHESTRATOR_A2A_URL missing in .env — run "
            "`python deployment/deploy.py orchestrator` (or `all`) first."
        )
    upstream = orchestrator_url.removesuffix("/.well-known/agent-card.json")
    bucket = f"{project}-a2a-gateway-agent-config"
    return project, upstream, bucket


def _upload_gateway_config(project: str, bucket: str, upstream: str) -> None:
    print(f"▶ Uploading gs://{bucket}/agents/{GATEWAY_AGENT_ID}.json → upstream {upstream}")
    _run_stream([
        "uv", "run", "python", "deployment/gateway/upsert_gcs_agent_config.py",
        "--project", project,
        "--bucket", bucket,
        "--prefix", "agents",
        "--agent-id", GATEWAY_AGENT_ID,
        "--backend-kind", "http_jsonrpc",
        "--upstream-base-url", upstream,
        "--name", "Truthfulness Orchestrator",
        "--description", GATEWAY_DESC,
        "--monthly-budget-usd", "50",
        "--estimated-cost-per-call-usd", "0.05",
        "--capture-call-content",
        "--capture-call-content-max-chars", "4000",
        "--forward-id-token",
    ])


def register_gateway() -> None:
    """Mint a new bearer token in Secret Manager + upload the gateway config."""
    project, upstream, bucket = _gateway_context()

    print("▶ Minting bearer token in Secret Manager...")
    _run_stream([
        "uv", "run", "python", "deployment/gateway/upsert_gateway_bearer_secret.py",
        "--project", project,
        "--secret-id", GATEWAY_SECRET_ID,
        "--grant-accessor-service-account", GATEWAY_SERVICE_ACCOUNT,
        "--print-token",
    ])
    print()
    _upload_gateway_config(project, bucket, upstream)
    print(
        "\n⚠  Copy the printed bearer token to your team vault AND paste it into .env as\n"
        "   A2A_GATEWAY_TRUTHFULNESS_ORCHESTRATOR_BEARER_TOKEN=<token>\n"
        "   (it is not stored anywhere else you can retrieve it later)."
    )


def update_gateway_config() -> None:
    """Re-upload the gateway config with the current orchestrator URL. Does not rotate the token."""
    project, upstream, bucket = _gateway_context()
    _upload_gateway_config(project, bucket, upstream)


def smoke_gateway() -> None:
    """End-to-end smoke via the gateway. Requires the four A2A_GATEWAY_* vars in .env."""
    _run_stream([
        "uv", "run", "--env-file", str(ENV_FILE),
        "python", "deployment/gateway/smoke_orchestrator.py",
    ])


# ── CLI ────────────────────────────────────────────────────────────────

DISPATCH = {
    "mcp":                   deploy_mcp,
    "zero-shot":             deploy_zero_shot,
    "fine-tuned":            deploy_fine_tuned,
    "explainer":             deploy_explainer,
    "orchestrator":          deploy_orchestrator,
    "register-gateway":      register_gateway,
    "update-gateway-config": update_gateway_config,
    "smoke-gateway":         smoke_gateway,
}

# Commands that don't need the bucket-bootstrap preflight and don't participate in `all`.
GATEWAY_COMMANDS = {"register-gateway", "update-gateway-config", "smoke-gateway"}


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "service",
        choices=list(DISPATCH.keys()) + ["all"],
        help="Service to deploy, or 'all' for the 5 services in dependency order, or a gateway command.",
    )
    args = parser.parse_args()

    # Gateway commands are one-off and don't touch the uploads bucket — skip
    # the preflight + deploy-loop framing entirely.
    if args.service in GATEWAY_COMMANDS:
        try:
            DISPATCH[args.service]()
        except subprocess.CalledProcessError as e:
            print(f"\n❌ {args.service} failed (exit {e.returncode}).", file=sys.stderr)
            return e.returncode
        return 0

    # Preflight: ensure the GCS upload bucket + runtime SA IAM binding exist
    # before any Cloud Run service is deployed. Idempotent — no-op when the
    # bucket + binding are already in place. On a fresh clone this is what
    # generates the bucket name and writes GCS_BUCKET back to .env, so the
    # subsequent deploys can inject GCS_BUCKET into MCP + orchestrator envs.
    print(f"\n{'=' * 60}\n▶ Preflight: GCS bucket + IAM\n{'=' * 60}", flush=True)
    rc = bootstrap_bucket.main()
    if rc != 0:
        print(
            f"\n❌ Bucket bootstrap failed (exit {rc}). Deploys aborted — "
            f"fix the GCS/IAM error above and re-run.",
            file=sys.stderr,
        )
        return rc

    targets = DEPLOY_ORDER if args.service == "all" else [args.service]

    for i, svc in enumerate(targets, 1):
        print(f"\n{'=' * 60}\n▶ {i}/{len(targets)}: deploy {svc}\n{'=' * 60}", flush=True)
        try:
            DISPATCH[svc]()
        except subprocess.CalledProcessError as e:
            print(
                f"\n❌ deploy {svc} failed (exit {e.returncode}). "
                f".env still has URLs for any service that already deployed; "
                f"fix and re-run from this service onward.",
                file=sys.stderr,
            )
            return e.returncode

    print(f"\n🎉 Deployed: {', '.join(targets)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
