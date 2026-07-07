# truthfulness-agent

Multi-agent system for binary truthfulness classification of political statements, built on Google ADK 2.0.

## Current state

Five services, fully wired and deployable to Cloud Run:

- **Orchestrator** (`agents/agent.py`) — root agent; entry point. Lives directly in `agents/` because it's always the entry. Delegates to the three sub-agents **over A2A** (no in-process import). Exposes one public REST entry — `POST /invoke` (multipart: `instruction` + `file`) — that handles the curl-with-file UX (see [Public entry: `/invoke`](#public-entry-invoke)).
- **Zero-shot Predictor** (`agents/zero_shot/`) — wraps the `predict_truthfulness_from_gcs(uri, use_fine_tuned=False)` MCP tool. The tool downloads a JSON batch from GCS and runs the zero-shot path.
- **Fine-tuned Predictor** (`agents/fine_tuned/`) — wraps the same MCP tool but always passes `use_fine_tuned=True`, routing inference through the Vertex AI tuned endpoint named in `FINE_TUNED_MODEL` (`.env`). When `FINE_TUNED_MODEL` is unset, the tool falls back to `FINE_TUNED_BASE_MODEL` (and logs a warning) so the wiring stays smoke-testable before the first SFT job finishes — use `make test-fine-tuned` against a running MCP server to verify. Fine-tuning jobs are submitted via the `fine_tune_truthfulness` MCP tool (or `make finetune`); the job name is auto-persisted to `LAST_TUNING_JOB` in `.env`, so the `check_finetune_status` MCP tool can later poll it and self-heal `FINE_TUNED_MODEL` when training completes.
- **Explainer** (`agents/explainer/`) — wraps the `explain_truthfulness_from_gcs(uri, use_fine_tuned=False)` MCP tool. Downloads the same JSON batch shape, calls the prediction layer for verdicts AND an independent free-form model for per-point natural-language explanations, in one call.
- **MCP tool server** (`mcp_server/`) — shared tool server consumed by all agents over Streamable HTTP. Exposes:
  - `predict_truthfulness(req)` / `explain_truthfulness(req)` — the original inline-data tools (still registered; used directly by tests / scripts).
  - `predict_truthfulness_from_gcs(uri, use_fine_tuned=None)` / `explain_truthfulness_from_gcs(uri, use_fine_tuned=None)` — GCS-variant tools used by the deployed sub-agents. Download from gs://, validate as `PredictRequest`/`ExplainRequest`, call the inline tool, return the response. Optional `use_fine_tuned` override lets each sub-agent force its own path regardless of what's in the uploaded file.
  - `fine_tune_truthfulness(req)`, `check_finetune_status()` — SFT submission and status polling.

`predict_truthfulness` is one tool with two paths chosen by the `use_fine_tuned` flag (default False = zero-shot). It also accepts an optional `labels` argument (a list of ground-truth booleans, one per point). When provided, the response includes a `metrics` dict alongside `predictions` with accuracy, precision, recall, f1, support, and a confusion matrix (treating True as the positive class). Without `labels`, `metrics` is `None`.

### End-to-end request flow (`/invoke` → sub-agent → MCP)

```
curl -F instruction=... -F file=@batch.json
        │
        ▼
  orchestrator /invoke handler:
    - reads multipart (instruction + file bytes)
    - uploads file to gs://$GCS_BUCKET/uploads/<uuid>.<ext>
    - self-POSTs an A2A message to http://localhost:$PORT/
      with text "<instruction>\n\nGCS URI: gs://..."
        │
        ▼
  orchestrator A2A handler → orchestrator LLM:
    - reads the instruction, routes via routing rules in agents/prompt.py
    - emits transfer_to_agent({agent_name: "<one of three sub-agents>"})
        │
        ▼
  sub-agent (RemoteA2aAgent, Cloud Run) → sub-agent LLM:
    - extracts the gs:// URI from the user message
    - emits the appropriate MCP tool call with uri=... + use_fine_tuned=true/false
        │
        ▼
  MCP server → predict_truthfulness_from_gcs / explain_truthfulness_from_gcs:
    - downloads the JSON file from GCS
    - validates as PredictRequest / ExplainRequest
    - runs the underlying predictor / explainer
    - returns PredictResponse / ExplainResponse
        │
        ▼
  response bubbles back up: tool → sub-agent → orchestrator → curl
        │
        ▼
  orchestrator deletes the GCS object (finally-block cleanup)
```

All five services have **per-service Cloud Run deploys** (one `Dockerfile` + `cloudbuild.yaml` per service, one `make deploy-<svc>` target each, all chained by `make deploy-all` via `deployment/deploy.py`). The orchestrator and three sub-agents speak A2A JSON-RPC; the MCP server speaks Streamable HTTP. See [Cloud deployment](#cloud-deployment).

## Layout

```
truthfulness-agent/
├── pyproject.toml
├── main.py                        # CLI client — the way you TALK TO the deployed system via the gateway. `make ask FILE=...` or `python main.py --help`
├── .gcloudignore                  # Build-context filter (excludes data/, notebooks/, .env*, scripts/)
├── data/                          # dataset lives here, gitignored
├── agents/
│   ├── agent.py                   # Orchestrator: root_agent + a2a_app on :8000, sub_agents=[fine_tuned, zero_shot, explainer]
│   ├── prompt.py                  # Orchestrator instruction
│   ├── Dockerfile                 # Cloud Run image for the orchestrator (lives here since orchestrator has no subdir)
│   ├── cloudbuild.yaml            # Cloud Build config; -f agents/Dockerfile
│   ├── zero_shot/
│   │   ├── agent.py               # root_agent + a2a_app (the A2A server entry)
│   │   ├── client.py              # zero_shot_remote_agent (RemoteA2aAgent for other agents to consume)
│   │   ├── prompt.py              # single ZERO_SHOT_INSTRUCTION
│   │   ├── tools.py               # MANIFEST: assembles MCP toolsets + local tools into `tools`
│   │   ├── Dockerfile             # Cloud Run image for the zero-shot agent
│   │   └── cloudbuild.yaml        # Cloud Build config; -f agents/zero_shot/Dockerfile
│   ├── fine_tuned/                # Same shape as zero_shot; backed by a fine-tuned Gemini model
│   │   ├── agent.py               # root_agent + a2a_app on :8002
│   │   ├── client.py              # fine_tuned_remote_agent (RemoteA2aAgent)
│   │   ├── prompt.py              # FINE_TUNED_INSTRUCTION
│   │   ├── tools.py               # MANIFEST
│   │   ├── Dockerfile             # Cloud Run image for the fine-tuned agent
│   │   └── cloudbuild.yaml        # Cloud Build config
│   └── explainer/                 # Same shape; classifies + explains verdicts in natural language
│       ├── agent.py               # root_agent + a2a_app on :8003
│       ├── client.py              # explainer_remote_agent (RemoteA2aAgent)
│       ├── prompt.py              # EXPLAINER_INSTRUCTION
│       ├── tools.py               # MANIFEST (wires the `explain_truthfulness` MCP tool)
│       ├── Dockerfile             # Cloud Run image for the explainer
│       └── cloudbuild.yaml        # Cloud Build config
├── services/                      # External-system client wrappers (top-level)
│   ├── vertex_client.py           # Module-level Vertex-mode genai.Client singleton
│   └── gcs_service.py             # GCSService (get-or-create bucket + upload a file)
├── schemas/                       # Pydantic request/response models shared between MCP tools and consumers
│   └── models.py                  # PredictRequest, PredictResponse, ExplainRequest, ExplainResponse, etc.
├── mcp_server/                    # Shared tool server (MCP, Streamable HTTP)
│   ├── server.py                  # TruthfulnessMcpServer class + composed `app` for uvicorn
│   ├── Dockerfile                 # Cloud Run image for the MCP server
│   ├── cloudbuild.yaml            # Cloud Build config; -f mcp_server/Dockerfile
│   ├── utils/                     # App-level service code + config used by the MCP tools
│   │   ├── config.py              # Hyperparams, paths, label map, system instruction, env-var reads
│   │   ├── dataset_processor.py   # DatasetProcessor (CSV → train/val/test JSONL in Vertex SFT format)
│   │   ├── tuning_manager.py      # TuningManager (Vertex SFT submit + poll + .env write-back)
│   │   └── metrics.py             # compute_metrics (binary accuracy/precision/recall/f1/confusion matrix)
│   └── tools/                     # One file per tool — thin wrappers over utils/ + services/
│       ├── predict.py                  # predict_truthfulness (unified — `use_fine_tuned` flag picks zero-shot vs tuned endpoint)
│       ├── explain.py                  # explain_truthfulness (predict + per-point natural-language explanation, same flags as predict)
│       ├── finetune.py                 # fine_tune_truthfulness (submit SFT)
│       └── check_finetune_status.py    # check_finetune_status (poll the last SFT job, auto-update FINE_TUNED_MODEL)
├── notebooks/                     # EDA + analysis (install via `make notebook`)
│   └── 01_exploratory_data_analysis.ipynb
└── scripts/
    └── finetune.py                # CLI orchestrator (`make split` / `make finetune`) — same services as the MCP tool
```

## Setup

Requires **Python 3.13** (pinned via `.python-version`; `uv sync` will install it automatically).

```bash
make install     # uv sync (creates the .venv from pyproject.toml + .python-version)
make auth        # gcloud Application Default Credentials — the GCP project is auto-detected from these
make configure   # copy .env.example → .env (only needed if you want to override model / location / project)
```

`GOOGLE_CLOUD_PROJECT`, `GOOGLE_CLOUD_LOCATION`, and `GOOGLE_GENAI_USE_VERTEXAI` are auto-populated in [agents/__init__.py](agents/__init__.py) from `google.auth.default()` — so as long as `gcloud auth application-default login` has been run, no env file is needed for those.

Place the dataset at `data/data.csv` (gitignored).

## Run locally

| Command                              | What it does                                                              |
| ------------------------------------ | ------------------------------------------------------------------------- |
| `make run-web`                       | Orchestrator + sub-agents in the **dev** ADK web UI on `:8080`            |
| `make run-agent NAME=zero_shot`      | Launch a single sub-agent in the dev web UI on `:8080`                    |
| `make run-a2a NAME=orchestrator`     | Expose the orchestrator over A2A on `:8000` (production-shaped entry — what the grader curls) |
| `make run-a2a NAME=zero_shot`        | Expose zero_shot over A2A on `:8001`                                      |
| `make run-a2a NAME=fine_tuned`       | Expose fine_tuned over A2A on `:8002`                                     |
| `make run-a2a NAME=explainer`        | Expose explainer over A2A on `:8003`                                      |
| `make run-mcp`                       | Shared MCP tool server on `:8004` (`/mcp` endpoint, Streamable HTTP)      |
| `make dev`                           | All local: `run-mcp` + 3 sub-agent A2A servers + `run-web` in parallel    |
| `make dev-cloud-mcp`                 | Local agents, **cloud MCP** (uses `MCP_SERVER_URL` from `.env`)           |
| `make dev-cloud-mcp-explainer`       | Local zero_shot + fine_tuned + web UI; **cloud MCP + explainer**          |
| `make dev-cloud-all`                 | Only the local web UI runs; **everything else is cloud** (orchestrator in-process delegates to deployed sub-agents → deployed MCP) |
| `make clean`                         | Wipe `.venv` and `__pycache__`                                            |
| `make notebook`                      | Install `notebook` extra (jupyterlab/seaborn/matplotlib/missingno/shap) and open JupyterLab in `notebooks/` |
| `make split`                         | Write `data/splits/{train,val,test}.jsonl` from `data.csv` (no GCS / no SFT) |
| `make finetune`                      | Full pipeline: split → upload to GCS → submit Vertex SFT → wait for completion (requires `GCS_BUCKET` in `.env`) |
| `make test-fine-tuned`               | Smoke-test the fine-tuned path of `predict_truthfulness` (`use_fine_tuned=True`); requires `make run-mcp`. Falls back to `FINE_TUNED_BASE_MODEL` when `FINE_TUNED_MODEL` is unset. |

### Port allocation

| Port | Server                | Env var                | Why                                  |
| ---- | --------------------- | ---------------------- | ------------------------------------ |
| 8000 | Orchestrator A2A      | `ORCHESTRATOR_A2A_PORT`| Production entry — grader curls here |
| 8001 | Zero-shot A2A         | `ZERO_SHOT_A2A_PORT`   |                                      |
| 8002 | Fine-tuned A2A        | `FINE_TUNED_A2A_PORT`  |                                      |
| 8003 | Explainer A2A         | `EXPLAINER_A2A_PORT`   |                                      |
| 8004 | MCP tool server       | `MCP_SERVER_PORT`      | `/mcp` — single endpoint, many tools |
| 8080 | ADK web UI (dev only) | — (hardcoded)          | Browser playground for iteration     |

### A2A endpoint

`make run-a2a NAME=<name>` looks up the port from `<AGENT_NAME_UPPER>_A2A_PORT` in `.env`. The Python `a2a_app` in the agent's `agent.py` reads the **same** env var, so the agent card's `url` matches the bind port automatically.

`NAME=orchestrator` is special-cased to `agents/agent.py` (orchestrator lives directly in `agents/`); every other agent resolves to `agents/<NAME>/agent.py`.

When all three A2A services are running:

| URL                                                            | What it returns                          |
| -------------------------------------------------------------- | ---------------------------------------- |
| `http://127.0.0.1:8000/.well-known/agent-card.json`            | Orchestrator AgentCard                   |
| `http://127.0.0.1:8000/`                                       | Orchestrator JSON-RPC endpoint           |
| `http://127.0.0.1:8001/.well-known/agent-card.json`            | Zero-shot AgentCard                      |
| `http://127.0.0.1:8001/`                                       | Zero-shot JSON-RPC endpoint              |

The card is built by ADK's `to_a2a()` helper directly from the `Agent(...)` definition — no manual `agent.json` is needed. Each agent module just needs `a2a_app = to_a2a(root_agent, port=int(os.environ["<NAME>_A2A_PORT"]))`.

### Test fixtures

`data/` contains small hand-curated JSON batches you can paste into the agent's chat:

| File                | Points | Labels | Use for                                |
| ------------------- | -----: | :----: | -------------------------------------- |
| `data/sample_1.json`  |      1 |        | Smoke test (one Obama statement)       |
| `data/sample_2.json`  |      2 |        | Smallest no-labels batch (verifies multi-point handling) |
| `data/sample_3.json`  |      3 |   ✓    | Mixed-label batch sanity check         |
| `data/sample_10.json` |     10 |   ✓    | Larger batch covering all 6 label classes |

Each file follows the PDF's request shape: `{"points": [...], "labels": [...]}` (the agent currently ignores `labels` — they'll be consumed when the metrics path comes back).

`data/test_prompts.txt` also contains five natural-language prompts mapped to each orchestrator routing rule — useful for quick smoke testing in the web UI or via curl.

## Cloud deployment

All five services deploy to Cloud Run via per-service Dockerfile + cloudbuild.yaml + Makefile target. Build context is always the repo root so each image can `COPY` shared modules (`services/`, `schemas/`).

| Command                       | Service                                     | Notes                                              |
| ----------------------------- | ------------------------------------------- | -------------------------------------------------- |
| `make deploy-mcp`             | `truthfulness-mcp` (MCP over HTTP)          | Deploy first — sub-agents need its URL             |
| `make deploy-zero-shot`       | `truthfulness-zero-shot` (A2A)              |                                                    |
| `make deploy-fine-tuned`      | `truthfulness-fine-tuned` (A2A)             |                                                    |
| `make deploy-explainer`       | `truthfulness-explainer` (A2A)              |                                                    |
| `make deploy-orchestrator`    | `truthfulness-orchestrator` (A2A)           | Deploy last — needs the three sub-agent URLs       |

After each deploy, the resulting URL is auto-written back to `.env` (`MCP_SERVER_URL` for MCP, `<NAME>_A2A_URL` for each agent). Subsequent agent deploys pick up those URLs as runtime env vars so each container knows where to find its dependencies.

### How discovery works

- **Sub-agents discover MCP** — each `tools.py` reads `MCP_SERVER_URL` (deployed) or falls back to `localhost:$MCP_SERVER_PORT` (local).
- **Orchestrator discovers sub-agents** — each `client.py` reads `<NAME>_A2A_URL` (deployed agent card URL) or falls back to localhost.
- **Each agent publishes its public URL in its agent card** — the deploy target injects `<NAME>_A2A_PUBLIC_HOST` / `_PROTOCOL` / `_PUBLIC_PORT` so `to_a2a()` advertises the public HTTPS URL instead of `http://0.0.0.0:<port>`.

All services deploy with `--allow-unauthenticated`. To lock down, flip to `--no-allow-unauthenticated` per target and grant `roles/run.invoker` to the calling SA on each downstream service.

### Public entry: `/invoke`

The orchestrator exposes one curl-friendly REST endpoint on top of its A2A surface:

```
POST <orchestrator-url>/invoke
Content-Type: multipart/form-data
  instruction: <free-form text — what to do with the file>
  file:        <the JSON batch you want classified / explained>
```

The handler uploads the file to `gs://$GCS_BUCKET/uploads/<uuid>.<ext>`, self-calls the orchestrator's A2A endpoint with `{instruction}\n\nGCS URI: gs://...`, the orchestrator's LLM routes to a sub-agent, the sub-agent calls the appropriate `*_from_gcs` MCP tool with the URI, response bubbles back, GCS object is deleted in a `finally` block. Whole thing runs in one HTTP round-trip from the caller's perspective.

**Three example curls** — same endpoint, three different `instruction` strings drive three different routing decisions:

```bash
# Predict (default → fine_tuned_predictor)
curl -X POST <orchestrator-url>/invoke \
  -F "instruction=please classify these statements" \
  -F "file=@data/sample_1.json" | python3 -m json.tool

# Explain (→ explainer)
curl -X POST <orchestrator-url>/invoke \
  -F "instruction=classify and explain each statement in detail" \
  -F "file=@data/sample_1.json" | python3 -m json.tool

# Zero-shot baseline (→ zero_shot_predictor)
curl -X POST <orchestrator-url>/invoke \
  -F "instruction=use the zero-shot baseline to classify these" \
  -F "file=@data/sample_2.json" | python3 -m json.tool
```

The response shape is `{"answer": "<final text>", "raw": <full A2A response>}`. The `answer` field is the orchestrator's final natural-language reply; the `raw` field carries the full A2A response including `result.status.state` (`completed` / `working` / `failed`), the full message history (you can see the `transfer_to_agent` and tool calls), and ADK token-usage metadata. Pipe to `python3 -m json.tool` to read it.

A compact "answer only" extractor:
```bash
curl -sS -X POST <orchestrator-url>/invoke \
  -F "instruction=please classify these statements" \
  -F "file=@data/sample_1.json" \
  | python3 -c 'import sys, json; r=json.load(sys.stdin); print("state:", r["raw"]["result"]["status"]["state"]); print("answer:", r["answer"])'
```

### A2A endpoint (still available)

The orchestrator's `to_a2a()` Starlette app also serves the raw A2A JSON-RPC endpoint at `POST /` and the agent card at `GET /.well-known/agent-card.json`, used by `RemoteA2aAgent` clients (other agents discovering this one) and by the ADK web UI. The `/invoke` route sits alongside these without affecting them — they're sibling URL paths on the same uvicorn process. Each sub-agent also exposes the same A2A endpoint shape — replace `<orchestrator-url>` with the sub-agent URL to talk to it directly, bypassing the orchestrator LLM's routing.

### Model env vars

Each agent reads its model from a `<NAME>_MODEL` env var with a `gemini-2.5-flash` fallback:

| Var                      | Read by                          | Notes                                                          |
| ------------------------ | -------------------------------- | -------------------------------------------------------------- |
| `ORCHESTRATOR_MODEL`     | Orchestrator agent               | Routes / delegates; never calls tools directly                 |
| `ZERO_SHOT_MODEL`        | Zero-shot agent + MCP predict tool | Same model used at both layers                                |
| `EXPLAINER_MODEL`        | Explainer agent + MCP explain tool | Same model used at both layers                                |
| `FINE_TUNED_AGENT_MODEL` | Fine-tuned **wrapper agent only**  | Routing/formatting layer                                       |
| `FINE_TUNED_MODEL`       | MCP `predict_truthfulness` tool only | The deployed Vertex AI tuned endpoint path (NOT a base model name) |
| `FINE_TUNED_BASE_MODEL`  | MCP `predict_truthfulness` tool, as fallback | Used when `FINE_TUNED_MODEL` is empty (e.g. before first SFT job) |

The two-layer split exists because the `fine_tuned` agent's wrapping LLM (routing) is conceptually distinct from the prediction endpoint it calls. For `zero_shot` and `explainer`, both layers use the same model, so a single env var is enough.

## Security

The deployed system enforces defense-in-depth on every hop. This section describes the full posture — what protects what, how requests actually flow, and how to bootstrap or verify the setup.

### Threat model

- **External callers** must authenticate with a static bearer token before their request can reach the orchestrator.
- **MCP + the three sub-agents** are not reachable from the public internet at all (silent 404 at Cloud Run's edge).
- **Only the orchestrator's Cloud Run service** can reach the sub-agents; only the sub-agents (and the orchestrator) can reach MCP.
- **Vertex AI + GCS + Secret Manager calls** stay on Google's private backbone (no traffic egresses the VPC).

### Request flow (bottom to top)

```
external caller  ──Authorization: Bearer <token> + X-A2A-Caller: <email>──▶  A2A Gateway (shared, europe-west1)
                                                                                    │
                                                            gateway validates bearer against Secret Manager
                                                            gateway mints Google ID token for orchestrator SA
                                                                                    ▼
                                                         orchestrator  (ingress=all, --no-allow-unauthenticated)
                                                            IAM check: gateway SA has roles/run.invoker ✓
                                                                                    │
                                                          orchestrator's outbound routed via default VPC
                                                                                    ▼
                                                       sub-agent  (ingress=internal, allow-unauthenticated)
                                                            edge check: arrived via VPC ✓
                                                                                    │
                                                            sub-agent's outbound routed via default VPC
                                                                                    ▼
                                                            MCP  (ingress=internal, allow-unauthenticated)
                                                            edge check: arrived via VPC ✓
                                                                                    │
                                                            MCP calls Vertex AI via Private Google Access
```

### Layer 1 — External access via the A2A Gateway

The orchestrator is fronted by the shared **A2A Agents Gateway** (`https://a2a-agent-gateway-eu-fq5fpdmt7a-ew.a.run.app`, owned by another research team, one instance for the whole org).

Callers hit `POST /agents/truthfulness-orchestrator/` with:

```
Authorization: Bearer <bearer-token>
X-A2A-Caller:  <caller@satalia.com>
Content-Type:  application/json

<A2A JSON-RPC body>
```

The gateway:

1. Validates the bearer against Secret Manager (`a2a-gateway-truthfulness-orchestrator-bearer-token`).
2. Enforces rate limit (10 rps per token) and monthly budget ($50/mo, $0.05/call configured).
3. Because our config has `forward_id_token: true`, mints a fresh short-lived Google ID token as its own SA (`a2a-agent-gateway@x-wppai-dataspine-choreo-dev.iam.gserviceaccount.com`).
4. Forwards to `https://truthfulness-orchestrator-<projnum>.europe-west1.run.app/` with the ID token in the `Authorization` header.

Bearer tokens live only in Secret Manager. They are never in `git`, in the gateway's GCS config, or in any deploy script. Values are handed to callers out-of-band (team vault, encrypted channel).

### Layer 2 — Orchestrator: IAM-locked Cloud Run

The orchestrator deploys with `--ingress=all --no-allow-unauthenticated`. Cloud Run's IAM edge rejects any request without a valid Google ID token whose identity has `roles/run.invoker` on this service. The only principal granted that role is the gateway's SA — no one else can invoke the orchestrator, not even from inside the project via curl.

Verification: direct curl to `https://truthfulness-orchestrator-<projnum>.europe-west1.run.app/.well-known/agent-card.json` from a laptop returns **403**.

### Layer 3 — Sub-agents + MCP: `--ingress=internal` + VPC egress

MCP and the three sub-agents deploy with `--ingress=internal`. Cloud Run's ingress edge only accepts requests that **arrive via a VPC network**, not the public frontend. That rules out any laptop, any external caller, and any Cloud Run service that isn't configured to route through the VPC.

To make the orchestrator → sub-agent and sub-agent → MCP hops actually reach their destinations, every calling Cloud Run service also deploys with:

```
--network=default --subnet=default --vpc-egress=all-traffic
```

`--vpc-egress=all-traffic` routes ALL outbound HTTPS from that service through the default VPC. That means calls to sibling Cloud Run services (which are what we want protected) go over the private network — matching what the destination's `--ingress=internal` filter allows through.

Verification: direct curl from a laptop to any of `truthfulness-mcp`, `truthfulness-zero-shot`, `truthfulness-fine-tuned`, `truthfulness-explainer` on their `.run.app` URLs returns **404** — the request is dropped at Cloud Run's edge before ever hitting the container. There are no destination-side logs.

### Private Google Access (PGA)

Because every service routes ALL outbound traffic through the VPC (including Vertex AI, GCS, and Secret Manager calls), the VPC subnet must have Private Google Access enabled — otherwise those calls to `*.googleapis.com` would fail (they resolve to public IPs which aren't in the VPC's private range).

Enable once, per subnet you use (default subnet in `europe-west1` for this project):

```
gcloud compute networks subnets update default \
  --region=europe-west1 --project=x-wppai-dataspine-choreo-dev \
  --enable-private-ip-google-access
```

Verify:

```
gcloud compute networks subnets describe default \
  --region=europe-west1 --project=x-wppai-dataspine-choreo-dev \
  --format='value(privateIpGoogleAccess)'
# expected: True
```

If PGA is off, every Vertex/GCS/Secret Manager call from every service breaks silently in the same way `--ingress=internal` breaks direct HTTPS — no error logs, requests just never leave the VPC. Do not disable PGA without also removing `--vpc-egress=all-traffic` from `deployment/deploy.py`.

### File-upload flow interaction (`/invoke`)

The [`/invoke` REST endpoint](#public-entry-invoke) sits INSIDE the same security perimeter — it's just a wrapper around the orchestrator's A2A `message/send`, so any request reaching `/invoke` has already passed the gateway bearer check and the IAM check.

Two operational requirements are specific to the file-upload flow:

- **Bucket must exist + IAM must be granted before first `/invoke` call.** Bootstrap via `make bootstrap-bucket` — idempotent, safe to re-run, creates `gs://<GCS_BUCKET>` in `<GCS_LOCATION>` if missing and grants the runtime compute SA `roles/storage.objectAdmin` on it. Chained into `make bootstrap` so onboarding is `make bootstrap && make deploy-all`.
- **Region alignment for the bucket matters.** Because the orchestrator delegates to a sub-agent via `transfer_to_agent(...)` and ADK 2.3.0 has a latency-sensitive async-event-queue that can drop late-arriving sub-agent responses, cross-region tool calls (e.g. europe-west1 Vertex + us-central1 bucket) may return an empty `answer`. Keep `GCS_BUCKET`, `GCS_LOCATION`, and `GOOGLE_CLOUD_LOCATION` all in the same region.

### CLI client — `main.py` (the way external callers talk to the system)

Because [`/invoke` is not reachable through the gateway](#file-upload-flow-interaction-invoke) (gateway is a JSON-RPC-only proxy), external callers use the two-step **upload-then-URI** pattern. `main.py` at the repo root wraps that pattern into one command.

`PROMPT` is always required — agents are instructed via natural language. `FILE` or `URI` are optional data sources (mutually exclusive; a plain inline `PROMPT` is fine too).

```
# Inline question, no file
make ask PROMPT="Classify: The Earth is flat."

# Classify a local file (auto-uploads to GCS, appends URI to the prompt)
make ask PROMPT="please classify and explain each statement" FILE=data/sample_1.json

# Same but the file is already in GCS
make ask PROMPT="please classify" URI=gs://truthfulness-sft-europe-west1/uploads/mine.json

# Steer the routing
make ask PROMPT="use the fine-tuned model" FILE=data/sample_3.json AGENT=fine_tuned
```

Equivalent raw `python main.py` invocations work too — see `python main.py --help` for the full flag surface. The client:

1. If `--file`, runs `gcloud storage cp <local> gs://$GCS_BUCKET/uploads/<uuid>.<ext>` under the hood.
2. Builds an A2A JSON-RPC `message/send` body that puts either the URI or the plain prompt in a `text` part.
3. POSTs to `$A2A_GATEWAY_BASE_URL/agents/$A2A_GATEWAY_AGENT_ID/` with `Authorization: Bearer <token>` + `X-A2A-Caller: <email>`.
4. Extracts the verdict text from the returned artifacts and prints it.

Uses only Python stdlib + the `gcloud` CLI — no extra dependencies. Any script or CI job can invoke `make ask ...` the same way you would locally.

### Bootstrap the security posture from scratch

One-time, per environment:

```
# 1. Enable Private Google Access on the default subnet.
gcloud compute networks subnets update default \
  --region=europe-west1 --project=x-wppai-dataspine-choreo-dev \
  --enable-private-ip-google-access

# 2. Onboard: creates .env, installs deps, gcloud ADC, provisions the GCS bucket + IAM.
make bootstrap

# 3. Deploy all 5 services (each picks up its ingress + vpc_egress from deployment/deploy.py).
make deploy-all

# 4. Register the orchestrator with the shared A2A Gateway.
#    Mints a bearer token in Secret Manager, grants gateway SA `secretAccessor`,
#    uploads the per-agent GCS config with forward_id_token=true.
make register-orchestrator-gateway
# — capture the printed bearer token, put it in the team vault, and paste into .env
#    as A2A_GATEWAY_TRUTHFULNESS_ORCHESTRATOR_BEARER_TOKEN

# 5. Populate .env with the four gateway vars:
#    A2A_GATEWAY_BASE_URL, A2A_GATEWAY_AGENT_ID, ..._BEARER_TOKEN, A2A_CALLER_EMAIL

# 6. Smoke test end-to-end through the gateway.
make smoke-orchestrator-gateway
```

### Verify the posture at any time

```
# Full-chain smoke — should return a real verdict.
make smoke-orchestrator-gateway

# From a laptop: all four sub-agent/MCP URLs should 404, orchestrator should 403.
PROJNUM=$(gcloud projects describe x-wppai-dataspine-choreo-dev --format='value(projectNumber)')
for svc in mcp zero-shot fine-tuned explainer; do
  echo "$svc: $(curl -sS -o /dev/null -w '%{http_code}' https://truthfulness-$svc-$PROJNUM.europe-west1.run.app/)"
done
echo "orchestrator: $(curl -sS -o /dev/null -w '%{http_code}' https://truthfulness-orchestrator-$PROJNUM.europe-west1.run.app/.well-known/agent-card.json)"
# expected: mcp 404, zero-shot 404, fine-tuned 404, explainer 404, orchestrator 403
```

If any URL returns 200 to a laptop, something has regressed. Common causes: someone flipped a service back to `--ingress=all`, PGA got disabled, or a new service was added without `--vpc-egress=all-traffic`.

### Updating the orchestrator URL in the gateway

When the orchestrator's URL changes (region migration, service rename), re-upload the gateway's GCS config so it points at the new upstream — this does NOT rotate the bearer token:

```
make update-orchestrator-gateway-config
```

Wait ~60s for the gateway's config cache to refresh (or click "Rescan config + usage" in the gateway's `/monitoring` UI), then re-smoke.

### Rotating the bearer token

Re-run the register target — it adds a new secret version and prints the new value. Old versions stay valid until manually disabled in Secret Manager. Paste the new token into your vault + `.env`, then old callers must be updated to use it.

```
make register-orchestrator-gateway   # prints new token; old callers keep working until versions are disabled
```

### What we deliberately did NOT do (and why)

- **We did NOT switch to `--no-allow-unauthenticated` + Google ID tokens on sub-agents/MCP.** That would work too and is Google's other recommended pattern (identity-based auth per hop instead of network-based). We chose ingress+VPC because it required zero application code changes — just deploy-script flags. If we later want per-caller audit trails (which SA called which sub-agent), or if this project grows to multi-project setups where VPC routing gets complex, switching to ID-token auth is the natural upgrade path.
- **We did NOT attach MCP tools directly to the orchestrator.** The multi-agent routing via `sub_agents` is the whole architectural point — orchestrator delegates, sub-agents call MCP tools. Attaching MCP tools directly would sidestep the ADK async-queue race but at the cost of the layered agent design. Instead we mitigate the race by keeping regions aligned (see file-upload flow section above).
- **We did NOT provision a dedicated VPC.** The default VPC works fine for a same-project setup. A dedicated VPC would add operational complexity without meaningfully better isolation for our threat model.
- **We did NOT add a Serverless VPC Access connector.** Direct VPC Egress is the modern replacement — no per-instance connector infra to maintain, no per-hour connector billing.

## Things we tried (and why we didn't ship them)

Three architectures we explored before landing on the current "one Cloud Run service per agent, one Dockerfile per agent, MCP as a sibling service" shape. Recording them so we don't re-discover the same dead-ends.

### 1. Vertex AI Agent Engine (Reasoning Engine)

Google's hosted ADK runtime, designed to let you deploy an `Agent(...)` object as a managed service without writing Dockerfiles or managing containers — sounds like the obvious choice for an ADK project.

**Why we backed off:** The framework is still immature for multi-agent A2A systems.
- Most of ADK's A2A primitives (`to_a2a`, `A2aAgentExecutor`, `RemoteA2aAgent`, `AgentCardBuilder`, `convert_*_to_a2a_part`, …) emit `UserWarning: [EXPERIMENTAL]` on every use. You can see them in our Cloud Run logs today. ADK acknowledges the API is subject to breaking changes.
- Agent Engine's deployment shape is opinionated toward single-agent setups; wiring an orchestrator with three `RemoteA2aAgent` sub-agents through it required workarounds that broke as soon as we redeployed.
- Debugging is harder — you don't have direct access to the container, logs flow through the Vertex Agent Engine console, and our local-vs-remote behavior diverged in ways that were hard to reproduce.

For a system in flux where we want to read logs, tail HTTP requests, override env vars, and iterate fast, **plain Cloud Run + uvicorn won**. Once ADK's A2A stack stabilizes (the EXPERIMENTAL flags drop), Agent Engine is worth a re-evaluation.

### 2. One Cloud Run service hosting all agents on internal ports

Idea: pack the orchestrator + 3 sub-agents + MCP into one container, each binding a different port (orchestrator on 8080, MCP on 8004, sub-agents on 8001/2/3), communicating via `localhost:<port>`. One service to deploy, one to monitor, "agents talk over loopback so it's fast".

**Why it didn't work cleanly:**
- **Cloud Run only exposes one port (`$PORT`) to the outside world.** Cloud Run's load balancer only routes external traffic to `$PORT` (default 8080). The other ports are bindable inside the container but unreachable from anywhere except the same container.
- That's not by itself a blocker — internal loopback between processes in the same container is supposed to work. In practice, **running 5 uvicorn processes under one container ENTRYPOINT in Cloud Run is fragile**: startup ordering races (orchestrator boots before sub-agents are listening), SIGTERM propagation (Cloud Run signals the container's PID 1, child processes may not exit cleanly), and the platform's startup TCP probe only checks one port.
- We hit symptoms that looked like loopback connection-refused / connection-reset under load — not because loopback itself is broken, but because the supervising process was racing the uvicorn instances behind it. Worth being aware that the popular "stick everything in one container" pattern has these gotchas in Cloud Run.

**What we shipped instead:** one Cloud Run service per agent. Each service binds `$PORT=8080` (Cloud Run convention), gets its own URL, and the only inter-agent communication is over the public Cloud Run network (with the orchestrator self-call still using localhost loopback inside its own single-uvicorn container, where the race doesn't exist).

### 3. One shared Dockerfile for all services

Idea: write one Dockerfile that builds the whole project (all deps, all source), then point each Cloud Run service at the same image with a different `--command`/`--args` override or env var to pick which agent to serve. Avoids maintaining 5 nearly-identical Dockerfiles.

**Why it didn't pan out:**
- Build-context bloat — every service got every other service's source baked into its image. The image was 2-3× the size it needed to be.
- Per-service `COPY` selectivity goes out the window — the orchestrator container shouldn't ship MCP's `predict_truthfulness` function with all of its `services/` / `schemas/` deps unless it needs them.
- The `--command` / `--args` override felt brittle: a typo in the deploy script silently boots the wrong agent into the wrong service slot.
- Cache invalidation got weird — any source change rebuilt every layer of the shared image, blocking the small per-service deploys we wanted.

**What we shipped instead:** per-service `Dockerfile` + `cloudbuild.yaml` under each service directory (`mcp_server/`, `agents/explainer/`, etc., plus `agents/Dockerfile` for the orchestrator). Each `COPY`s only the source paths it actually needs. The build context is still the repo root so shared modules (`services/`, `schemas/`) can be selectively included. The `deployment/deploy.py` script holds the per-service env-var configuration; each `make deploy-<svc>` target is a one-liner that hands off to it.

---

## Label mapping

Six-way human labels are mapped to a binary target as follows:

- **True** ← `true`, `mostly-true`, `half-true`
- **False** ← `barely-true`, `false`, `extremely-false`
