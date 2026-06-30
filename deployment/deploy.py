#!/usr/bin/env python3
"""Deploy the truthfulness-agent Cloud Run services.

Holds the full deploy logic (Artifact Registry probe, Cloud Build, Cloud Run
deploy with the right `--set-env-vars`, write-back of the deployed URL to
`.env`) so the Makefile targets stay one-liners.

Usage:
    python deployment/deploy.py mcp           # one service
    python deployment/deploy.py zero-shot
    python deployment/deploy.py fine-tuned
    python deployment/deploy.py explainer
    python deployment/deploy.py orchestrator
    python deployment/deploy.py all           # all five in dependency order

Or via the Makefile wrappers:
    make deploy-mcp   /   make deploy-all   /   ...

Dependency order for `all`:
    1. truthfulness-mcp          (sub-agents read MCP_SERVER_URL)
    2. truthfulness-zero-shot
    3. truthfulness-fine-tuned
    4. truthfulness-explainer
    5. truthfulness-orchestrator (reads the three sub-agents' *_A2A_URL)

Each step writes its deployed URL back to `.env`, so later steps in this
sequence pick up the URLs the earlier steps just produced.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

from dotenv import dotenv_values, set_key

REPO_ROOT = Path(__file__).resolve().parent.parent
ENV_FILE = REPO_ROOT / ".env"
REPO = "cloud-run-source-deploy"

# Order matters when deploying "all":
DEPLOY_ORDER = ["mcp", "zero-shot", "fine-tuned", "explainer", "orchestrator"]


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
) -> str:
    """Deploy a Cloud Run service. Returns its public HTTPS URL."""
    print(f"▶ Deploying {service_name} to Cloud Run in {location}...")
    env_str = ",".join(f"{k}={v}" for k, v in env_vars.items())
    url = _run_capture([
        "gcloud", "run", "deploy", service_name,
        f"--image={image}",
        f"--region={location}",
        f"--project={project}",
        "--allow-unauthenticated",
        f"--set-env-vars={env_str}",
        "--format=value(status.url)",
    ]).strip()
    print(f"✅ Deployed: {url}")
    return url


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
        env_vars={
            **_gcp_env(env),
            "ORCHESTRATOR_MODEL": env.get("ORCHESTRATOR_MODEL", ""),
            "EXPLAINER_A2A_URL": env.get("EXPLAINER_A2A_URL", ""),
            "FINE_TUNED_A2A_URL": env.get("FINE_TUNED_A2A_URL", ""),
            "ZERO_SHOT_A2A_URL": env.get("ZERO_SHOT_A2A_URL", ""),
            **_public_a2a_env("ORCHESTRATOR", public_host),
        },
    )
    _write_env("ORCHESTRATOR_A2A_URL", f"{url}/.well-known/agent-card.json")


# ── CLI ────────────────────────────────────────────────────────────────

DISPATCH = {
    "mcp":          deploy_mcp,
    "zero-shot":    deploy_zero_shot,
    "fine-tuned":   deploy_fine_tuned,
    "explainer":    deploy_explainer,
    "orchestrator": deploy_orchestrator,
}


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "service",
        choices=list(DISPATCH.keys()) + ["all"],
        help="Service to deploy, or 'all' for all in dependency order.",
    )
    args = parser.parse_args()

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
