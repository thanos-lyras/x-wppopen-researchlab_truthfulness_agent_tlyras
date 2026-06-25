# truthfulness-agent

Multi-agent system for binary truthfulness classification of political statements, built on Google ADK 2.0.

## Current state

Four agents are wired up so far:

- **Orchestrator** (`agents/agent.py`) — root agent; entry point. Lives directly in `agents/` because it's always the entry. Delegates to the zero-shot predictor **over A2A** (no in-process import).
- **Zero-shot Predictor** (`agents/zero_shot/`) — wraps a pure-LLM `predict_truthfulness(points)` tool (temperature=0). Each non-orchestrator agent gets its own subfolder.
- **Fine-tuned Predictor** (`agents/fine_tuned/`) — same architecture as zero-shot. Calls the same unified `predict_truthfulness` MCP tool but with `use_fine_tuned=True`, which routes inference through the Vertex AI tuned model named in `FINE_TUNED_MODEL` (`.env`). When `FINE_TUNED_MODEL` is unset, the tool falls back to `FINE_TUNED_BASE_MODEL` (and logs a warning) so the wiring stays smoke-testable before the first SFT job finishes — use `make test-fine-tuned` against a running MCP server to verify. Fine-tuning jobs are submitted via the `fine_tune_truthfulness` MCP tool (or `make finetune`); the job name is auto-persisted to `LAST_TUNING_JOB` in `.env`, so the `check_finetune_status` MCP tool can later poll it and self-heal `FINE_TUNED_MODEL` when training completes. `check_finetune_status` updates both `.env` (for next boot) and the running process's environment, so the very next `predict_truthfulness(..., use_fine_tuned=True)` call hits the new endpoint — no MCP server restart needed.

`predict_truthfulness` is one tool with two paths chosen by the `use_fine_tuned` flag (default False = zero-shot). It also accepts an optional `labels` argument (a list of ground-truth booleans, one per point). When provided, the response includes a `metrics` dict alongside `predictions` with accuracy, precision, recall, f1, support, and a confusion matrix (treating True as the positive class). Without `labels`, `metrics` is `None`.
- **Explainer** (`agents/explainer/`) — same architecture as the predictors. Wired to a future `explain_truthfulness` MCP tool (not yet implemented).

Because the orchestrator now talks to zero_shot over A2A, **the zero_shot A2A server must be running** when you exercise the orchestrator. Use `make dev` (runs both in parallel) as your default dev command.

Full orchestrator wiring of the fine-tuned predictor and explainer, the `explain_truthfulness` MCP tool, and cloud deployment are intentionally not included yet.

## Layout

```
truthfulness-agent/
├── pyproject.toml
├── main.py
├── data/                          # dataset lives here, gitignored
├── agents/
│   ├── agent.py                   # Orchestrator: root_agent + a2a_app on :8000, sub_agents=[fine_tuned_remote_agent, zero_shot_remote_agent, explainer_remote_agent]
│   ├── prompt.py                  # Orchestrator instruction
│   ├── zero_shot/
│   │   ├── agent.py               # root_agent + a2a_app (the A2A server entry)
│   │   ├── client.py              # zero_shot_remote_agent (RemoteA2aAgent for other agents to consume)
│   │   ├── prompt.py              # single ZERO_SHOT_INSTRUCTION
│   │   └── tools.py               # MANIFEST: assembles MCP toolsets + local tools into `tools`
│   ├── fine_tuned/                # Same shape as zero_shot; backed by a fine-tuned Gemini model
│   │   ├── agent.py               # root_agent + a2a_app on :8002
│   │   ├── client.py              # fine_tuned_remote_agent (RemoteA2aAgent)
│   │   ├── prompt.py              # FINE_TUNED_INSTRUCTION
│   │   └── tools.py               # MANIFEST
│   └── explainer/                 # Same shape; explains verdicts in natural language
│       ├── agent.py               # root_agent + a2a_app on :8003
│       ├── client.py              # explainer_remote_agent (RemoteA2aAgent)
│       ├── prompt.py              # EXPLAINER_INSTRUCTION
│       └── tools.py               # MANIFEST (wires the future `explain_truthfulness` MCP tool)
├── services/                      # External-system client wrappers (top-level)
│   ├── vertex_client.py           # Module-level Vertex-mode genai.Client singleton
│   └── gcs_service.py             # GCSService (get-or-create bucket + upload a file)
├── mcp_server/                    # Shared tool server (MCP, Streamable HTTP)
│   ├── server.py                  # TruthfulnessMcpServer class + composed `app` for uvicorn
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
| `make dev`                           | `run-mcp` + `run-a2a NAME=zero_shot` + `run-web` in parallel              |
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

## Label mapping

Six-way human labels are mapped to a binary target as follows:

- **True** ← `true`, `mostly-true`, `half-true`
- **False** ← `barely-true`, `false`, `extremely-false`
