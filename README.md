# Truthfulness Agent

The **Truthfulness Agent** is a multi-agent system for binary truthfulness classification of political statements, built on the [Google Agent Development Kit (ADK 2.0)](https://github.com/google/adk-python).

An orchestrator routes each request to one of three specialist sub-agents — zero-shot, fine-tuned, or explainer — over A2A. All three delegate their model calls to a shared MCP tool server. The full stack deploys to Cloud Run behind the shared A2A Agents Gateway, so external callers hit a single bearer-authenticated JSON-RPC endpoint.

## 🚀 Features

- **Multi-agent orchestration** — an orchestrator LLM reads the caller's instruction and routes to one of three specialists over A2A (no in-process imports).
- **Two predictor paths** — zero-shot Gemini (baseline) and fine-tuned Gemini (Vertex SFT-trained on the project's data split). Selected by the `use_fine_tuned` flag or by routing rule.
- **Predict + explain in one call** — the explainer sub-agent returns both the verdict and a 2-3 sentence natural-language justification per point.
- **Metrics on request** — pass ground-truth `labels` alongside the statements and the response includes accuracy, precision, recall, f1, and a confusion matrix (True as the positive class).
- **Fine-tuning pipeline** — one MCP tool (`fine_tune_truthfulness`) handles stratified 80/10/10 split → GCS staging → Vertex SFT job submission. A companion tool (`check_finetune_status`) polls the job and self-heals `FINE_TUNED_MODEL` when the endpoint is ready.
- **File-upload entrypoint** — the orchestrator exposes `POST /invoke` (multipart: `instruction` + `file`) that uploads to GCS, self-invokes the A2A endpoint with the URI, and cleans up after. Larger-than-context batches move over GCS instead of the LLM message body.
- **Terraform + Python deploy** — one `terraform apply` provisions the bucket + Artifact Registry + VPC PGA + all 5 Cloud Run services + gateway registration end-to-end.
- **Defense-in-depth network posture** — MCP + 3 sub-agents run with `--ingress=internal`; orchestrator is IAM-locked (`--no-allow-unauthenticated`) with only the A2A Gateway service account granted invoker. All outbound traffic routes through the default VPC via `--vpc-egress=all-traffic`.
- **Per-hop OIDC auth** — every service-to-service call (orchestrator → sub-agent, sub-agent → MCP) mints a Google-signed ID token for the target's URL and attaches it as `Authorization: Bearer <token>`. Cloud Run's IAM edge validates each hop's compute-SA identity. Removes the dependency on `allUsers → run.invoker` bindings, which some GCP orgs block via `iam.allowedPolicyMemberDomains`.

## 🛠 Prerequisites

- Python 3.13+ (pinned via `.python-version`; `uv sync` installs it)
- [uv](https://github.com/astral-sh/uv) — Python package manager
- Google Cloud CLI (`gcloud`) installed + `gcloud auth application-default login`
- [Terraform](https://developer.hashicorp.com/terraform/install) ≥ 1.6 (for the cloud deploy)
- GCP project with billing enabled + these APIs on: `run`, `cloudbuild`, `artifactregistry`, `secretmanager`, `compute`, `storage`, `aiplatform`

## 📦 Installation & Setup

```bash
make bootstrap          # configure + install + auth (one command)
```

Then edit `.env` to set `GOOGLE_CLOUD_PROJECT` (everything else has sensible defaults). Auto-populated values (`GCS_BUCKET`, service URLs, gateway bearer) get written by the deploy scripts — leave those blank on a fresh clone.

Place the training dataset at `data/data.csv` (gitignored).

### 💻 Running Locally

The full local stack — MCP server + 3 sub-agent A2A servers + orchestrator + browser playground — spins up with one command:

```bash
make dev
```

Access the ADK web UI at `http://localhost:8080` and paste JSON batches into the chat. For finer control:

| Command                       | What it does                                                                                            |
| ----------------------------- | ------------------------------------------------------------------------------------------------------- |
| `make run-mcp`              | MCP tool server only (port 8004,`/mcp` endpoint)                                                      |
| `make run-a2a NAME=<agent>` | Expose one agent as A2A (`<agent>` ∈ `zero_shot`, `fine_tuned`, `explainer`, `orchestrator`) |
| `make run-web`              | Browser playground only                                                                                 |

Sample JSON batches under `data/sample_{1,2,3,10}.json` are ready to paste into the UI.

### ☁️ Deploying to Cloud Run

The full stack — GCS bucket + Artifact Registry + VPC Private Google Access + 5 Cloud Run services + gateway registration — deploys via one Terraform apply:

```bash
cp terraform/terraform.tfvars.example terraform/terraform.tfvars
# Edit terraform.tfvars: set project_id + region + bucket_name

make tf-init
make tf-apply       # ~15-20 min end-to-end
```

Under the hood, Terraform declaratively provisions the shared infra, then triggers `deployment/deploy.py all` which builds 5 images via Cloud Build, deploys each service with the right ingress/VPC/env-var posture, and registers the orchestrator with the A2A Agents Gateway. The bearer token + 5 service URLs get written back into `.env` automatically.

**Bypassing Terraform** — you can skip Terraform entirely with `make deploy-all`, useful when iterating on a single service. Terraform-owned infra (bucket, AR, PGA) must already exist.

**Smoke test after deploy:**

```bash
make smoke-orchestrator-gateway   # 3× 200 across health, agent card, JSON-RPC verdict
```

**Invoke the deployed system:**

```bash
make ask PROMPT="please classify and explain each statement" FILE=data/sample_1.json
```

### 🔒 How service-to-service auth works

Every hop between services (orchestrator → sub-agent, sub-agent → MCP) is IAM-checked and signed. There are no `allUsers` bindings anywhere — deliberately, because org policy `iam.allowedPolicyMemberDomains` typically blocks them in enterprise GCP orgs.

The pattern for each hop:

1. Caller (a Cloud Run service) mints a **Google-signed OIDC ID token** bound to the target service's base URL, using its own compute service account credentials from the metadata server. Handled by [`services/gcp_auth.py`](services/gcp_auth.py) — `IdTokenAuth` (httpx auth flow) for the `RemoteA2aAgent` clients, and a `header_provider` callback for the `McpToolset` connections.
2. The token rides on the request as `Authorization: Bearer <token>`.
3. Cloud Run's IAM edge on the target service validates the token, extracts the caller's SA identity, and checks whether that SA has `roles/run.invoker` on the target.
4. `terraform apply` grants the runtime compute SA (`<projnum>-compute@developer.gserviceaccount.com`) `roles/run.invoker` on MCP + the 3 sub-agents automatically. No manual IAM setup needed.

**Local dev is untouched** — [`services/gcp_auth.py`](services/gcp_auth.py) has an `is_cloud_run_url()` guard that skips token minting for `localhost` URLs, so `make dev` works over plain HTTP without ADC gymnastics.

**What this replaced.** The original design ran sub-agents with `--allow-unauthenticated` (network-only auth via `--ingress=internal` + VPC egress) — simpler code, but relies on the org allowing `allUsers` bindings. When our org's `iam.allowedPolicyMemberDomains` policy blocked those bindings on fresh service creation, we moved to per-hop OIDC. Same defense-in-depth (ingress-internal + VPC egress still applies), plus per-hop identity claims in Cloud Run logs, minus the dependency on an admin-granted policy exception.

## 📂 Project Structure

```text
truthfulness-agent/
├── main.py                          # CLI client for the deployed system (make ask)
├── agents/
│   ├── agent.py                     # Orchestrator: root_agent + a2a_app + POST /invoke
│   ├── prompt.py                    # Orchestrator routing rules
│   ├── zero_shot/                   # Zero-shot predictor sub-agent
│   ├── fine_tuned/                  # Fine-tuned predictor sub-agent
│   └── explainer/                   # Verdict + explanation sub-agent
│       ├── agent.py                 #   root_agent + a2a_app (A2A server entry)
│       ├── client.py                #   RemoteA2aAgent — how the orchestrator consumes this agent
│       ├── prompt.py                #   agent instruction
│       ├── tools.py                 #   MCP toolset manifest
│       ├── Dockerfile
│       └── cloudbuild.yaml
├── mcp_server/                      # Shared MCP tool server (Streamable HTTP)
│   ├── server.py                    # TruthfulnessMcpServer + composed Starlette app
│   ├── utils/                       # config.py, dataset_processor.py, tuning_manager.py, metrics.py
│   └── tools/                       # predict.py, explain.py, finetune.py, check_finetune_status.py
├── services/                        # External-system client wrappers
│   ├── vertex_client.py             # Module-level genai.Client singleton (Vertex mode)
│   └── gcs_service.py               # GCSService (bucket bootstrap + upload/download)
├── schemas/models.py                # Pydantic request/response models
├── deployment/                      # Deploy CLI: 5 Cloud Run services + gateway registration
│   ├── deploy.py                    # `python deployment/deploy.py [all|<svc>|register-gateway|…]`
│   └── gateway/                     # Bearer + gateway-config helpers (invoked from deploy.py)
├── terraform/                       # main.tf + variables.tf + outputs.tf
├── scripts/                         # CLI wrappers for SFT (finetune, sync-tuned-model, test-fine-tuned)
├── notebooks/                       # EDA + analysis
├── Makefile
└── pyproject.toml
```

## 🔀 End-to-end Request Flow

```
external caller ─── Bearer + X-A2A-Caller ──▶ A2A Gateway (shared, europe-west1)
                                                     │
                                       gateway validates bearer against Secret Manager
                                       gateway mints Google ID token for orchestrator SA
                                                     ▼
                                     Orchestrator (ingress=all, --no-allow-unauthenticated)
                                       LLM routes via transfer_to_agent(agent_name=…)
                                                     │
                                              routed over VPC
                                                     ▼
                                     Sub-agent (ingress=internal, allow-unauthenticated)
                                       LLM extracts gs:// URI + calls MCP tool
                                                     │
                                              routed over VPC
                                                     ▼
                                     MCP tool (predict / explain from_gcs)
                                       downloads batch → runs model → returns result
```

## 🧪 Things We Tried (and why we didn't ship them)

Three architectures we explored before landing on the current "one Cloud Run service per agent, MCP as a sibling, Terraform orchestrating" shape. Recording them so we don't rediscover the same dead-ends.

**1. Vertex AI Agent Engine (Reasoning Engine).** Google's hosted ADK runtime — no Dockerfiles, managed service. The obvious choice on paper. In practice, ADK's A2A primitives (`to_a2a`, `RemoteA2aAgent`, `A2aAgentExecutor`) still emit `UserWarning: [EXPERIMENTAL]` on every use, and Agent Engine's deployment shape is opinionated toward single-agent setups. Wiring an orchestrator with three `RemoteA2aAgent` sub-agents required workarounds that broke on redeploy. Debugging was hard — no direct container access, logs routed through the Agent Engine console, local-vs-remote behavior diverged. Plain Cloud Run + uvicorn won for iteration speed. Worth re-evaluating once the EXPERIMENTAL flags drop.

**2. One Cloud Run service hosting all agents on internal ports.** Pack the orchestrator + 3 sub-agents + MCP into one container, each binding a different port, communicating over `localhost`. Cloud Run only exposes one port externally, but internal loopback should still work. It didn't cleanly — running 5 uvicorn processes under one container ENTRYPOINT hit startup-ordering races, SIGTERM propagation issues, and the platform's TCP probe only checks one port. Under load we saw loopback connection-refused / reset — not because loopback was broken, but because a supervising process was racing behind it. Shipped instead: one Cloud Run service per agent; the orchestrator's `/invoke` self-call is the only remaining loopback and lives in a single-uvicorn container where the race doesn't exist.

**3. One shared Dockerfile for all services.** Build the whole project once, point each Cloud Run service at the same image with a different `--command` override to pick which agent to serve. Would avoid maintaining 5 near-identical Dockerfiles. Didn't pan out: image bloat (every service shipped every other service's source), per-service `COPY` selectivity lost, `--command` overrides were brittle (typo → wrong agent in wrong slot), and cache invalidation rebuilt everything on any source change. Shipped instead: per-service `Dockerfile` + `cloudbuild.yaml` under each service directory. Each copies only what it needs. Build context is still the repo root so `services/` + `schemas/` can be selectively included. `deployment/deploy.py` holds the per-service env-var configuration.

## Label mapping

Six-way human labels map to a binary target:

- **True** ← `true`, `mostly-true`, `half-true`
- **False** ← `barely-true`, `false`, `extremely-false`
