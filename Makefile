SHELL := /bin/bash
UV := uv
ENV_FILE := .env

# Create .env from .env.example if it's missing
configure:
	@if [ ! -f $(ENV_FILE) ]; then \
		cp .env.example $(ENV_FILE); \
		echo "Created $(ENV_FILE) from .env.example. Please UPDATE it."; \
	fi

# Authenticate with Google Cloud Application Default Credentials
auth:
	gcloud auth application-default login

# Install dependencies
install:
	$(UV) sync

# Install the notebook extra (pandas / seaborn / jupyterlab / sklearn) and launch JupyterLab.
notebook:
	$(UV) sync --extra notebook
	$(UV) run --extra notebook jupyter lab notebooks/

# Write data/splits/{train,val,test}.jsonl from data.csv (no GCS / no SFT).
split:
	PYTHONPATH=. $(UV) run --env-file $(ENV_FILE) python -m scripts.finetune --split-only

# Full fine-tuning: split → upload to GCS → submit Vertex SFT → wait for completion.
# Requires GCS_BUCKET set in .env. Job runs 30-90 min and costs a few dollars.
# On success, writes FINE_TUNED_MODEL=… to .env automatically.
finetune:
	PYTHONPATH=. $(UV) run --env-file $(ENV_FILE) python -m scripts.finetune

# Poll a previously-submitted SFT job until it finishes; on success writes
# FINE_TUNED_MODEL=… to .env. Use after `python -m scripts.finetune --no-wait`
# or the MCP tool with `wait=false`.
#   Usage:  make sync-tuned-model JOB=projects/.../tuningJobs/<id>
sync-tuned-model:
	@if [ -z "$(JOB)" ]; then echo "❌ JOB=projects/.../tuningJobs/<id> required"; exit 1; fi
	PYTHONPATH=. $(UV) run --env-file $(ENV_FILE) python -m scripts.sync_tuned_model $(JOB)

# Dev-only browser playground for the Orchestrator + its sub-agents on :8080.
# Production traffic should hit the Orchestrator's A2A endpoint instead (port 8000).
run-web:
	PYTHONPATH=. $(UV) run --env-file $(ENV_FILE) adk web --reload_agents --port 8080 agents

# Dev-only browser playground for a single sub-agent: `make run-agent NAME=zero_shot` on :8080.
NAME ?= zero_shot
run-agent:
	PYTHONPATH=. $(UV) run --env-file $(ENV_FILE) adk web --reload_agents --port 8080 agents/$(NAME)

# Expose an agent as an A2A service via uvicorn: `make run-a2a NAME=zero_shot`
# Port comes from <AGENT_NAME_UPPER>_A2A_PORT in .env.
# Special case: NAME=orchestrator → agents.agent (lives directly in agents/).
# Other agents     → agents.<NAME>.agent.
# Agent card: http://127.0.0.1:<port>/.well-known/agent-card.json
run-a2a:
	@set -a; source $(ENV_FILE); set +a; \
	PORT_VAR=$$(echo $(NAME) | tr a-z A-Z)_A2A_PORT; \
	PORT=$${!PORT_VAR}; \
	if [ -z "$$PORT" ]; then echo "❌ $$PORT_VAR is not set in $(ENV_FILE)"; exit 1; fi; \
	if [ "$(NAME)" = "orchestrator" ]; then MODULE=agents.agent:a2a_app; else MODULE=agents.$(NAME).agent:a2a_app; fi; \
	echo "▶ Exposing $(NAME) on port $$PORT (from $$PORT_VAR, module $$MODULE)"; \
	PYTHONPATH=. $(UV) run --env-file $(ENV_FILE) uvicorn $$MODULE --host 0.0.0.0 --port $$PORT --reload

# Run the shared MCP tool server (predict, explain, …) over Streamable HTTP.
# Port comes from MCP_SERVER_PORT in .env.
# Endpoint: http://127.0.0.1:<MCP_SERVER_PORT>/mcp
run-mcp:
	@set -a; source $(ENV_FILE); set +a; \
	if [ -z "$$MCP_SERVER_PORT" ]; then echo "❌ MCP_SERVER_PORT is not set in $(ENV_FILE)"; exit 1; fi; \
	echo "▶ MCP tool server on port $$MCP_SERVER_PORT (endpoint /mcp)"; \
	PYTHONPATH=. $(UV) run --env-file $(ENV_FILE) uvicorn mcp_server.server:app --host 0.0.0.0 --port $$MCP_SERVER_PORT --reload

# Cloud Run deploys. The full logic lives in `deployment/deploy.py` so these
# targets stay one-liners. Each deploy:
#   - ensures the Artifact Registry repo exists
#   - builds the image via Cloud Build (per-service cloudbuild.yaml + Dockerfile)
#   - deploys to Cloud Run with the right --set-env-vars
#   - writes the resulting URL back to .env so dependent services pick it up
#
# Run individual deploys in any order, or use `make deploy-all` to do all five
# in the right dependency order (mcp first, sub-agents next, orchestrator last).
deploy-mcp:
	$(UV) run python deployment/deploy.py mcp

deploy-zero-shot:
	$(UV) run python deployment/deploy.py zero-shot

deploy-fine-tuned:
	$(UV) run python deployment/deploy.py fine-tuned

deploy-explainer:
	$(UV) run python deployment/deploy.py explainer

deploy-orchestrator:
	$(UV) run python deployment/deploy.py orchestrator

# All five in dependency order: mcp → zero-shot → fine-tuned → explainer → orchestrator.
deploy-all:
	$(UV) run python deployment/deploy.py all

# Smoke-test the predict_fine_tuned_truthfulness MCP tool end-to-end.
# Requires `make run-mcp` running in another terminal.
# When FINE_TUNED_MODEL is unset, the tool falls back to FINE_TUNED_BASE_MODEL.
test-fine-tuned:
	PYTHONPATH=. $(UV) run --env-file $(ENV_FILE) python -m scripts.test_predict_fine_tuned

# Per-agent shorthand wrappers so `make dev`/`make dev-no-ui` can spin up
# A2A backends in parallel (Make can't invoke the same target twice with
# different args inside one -j run).
run-a2a-zero-shot:
	$(MAKE) run-a2a NAME=zero_shot
run-a2a-fine-tuned:
	$(MAKE) run-a2a NAME=fine_tuned
run-a2a-explainer:
	$(MAKE) run-a2a NAME=explainer
run-a2a-orchestrator:
	$(MAKE) run-a2a NAME=orchestrator

# Parallel dev stack: MCP (:8004) + zero_shot A2A (:8001) + fine_tuned A2A (:8002) +
# explainer A2A (:8003) + browser playground (:8080).
# The web UI on :8080 lets you chat with the orchestrator, which delegates to all three
# sub-agents over A2A — so all three backends must be up. Start the orchestrator's own
# A2A endpoint (:8000) separately when you need production-shape curl access:
#     make run-a2a NAME=orchestrator
dev:
	$(MAKE) -j 5 run-mcp run-a2a-zero-shot run-a2a-fine-tuned run-a2a-explainer run-web

# Same as `dev` but skips the local MCP — agents resolve tools via the deployed
# Cloud Run MCP (MCP_SERVER_URL in .env, written by `make deploy-mcp`).
# Use after `make deploy-mcp` to validate the local agents against the live MCP.
dev-cloud-mcp:
	$(MAKE) -j 4 run-a2a-zero-shot run-a2a-fine-tuned run-a2a-explainer run-web

# Like `dev-cloud-mcp` but ALSO skips the local explainer A2A — the orchestrator
# routes to the deployed explainer (EXPLAINER_A2A_URL in .env, written by
# `make deploy-explainer`). zero_shot + fine_tuned still run locally; both they
# and the deployed explainer hit the deployed MCP. Use after `make deploy-mcp`
# AND `make deploy-explainer` to validate cross-service A2A.
dev-cloud-mcp-explainer:
	$(MAKE) -j 3 run-a2a-zero-shot run-a2a-fine-tuned run-web

# Fully cloud: NO local A2A processes — only the browser UI runs locally.
# The orchestrator (in-process inside `adk web`) routes every sub-agent call
# to its deployed Cloud Run service via the *_A2A_URL env vars in .env; those
# services in turn hit the deployed MCP. Use after `make deploy-mcp`,
# `make deploy-zero-shot`, `make deploy-fine-tuned`, AND `make deploy-explainer`.
dev-cloud-all:
	$(MAKE) run-web

# Same as `dev` but no browser UI — orchestrator A2A on :8000 takes the slot
# instead, so you can curl the orchestrator directly:
#   curl -sS -X POST http://localhost:8000/ ...
dev-no-ui:
	$(MAKE) -j 5 run-mcp run-a2a-zero-shot run-a2a-fine-tuned run-a2a-explainer run-a2a-orchestrator

# Cleanup the venv and Python caches
clean:
	rm -rf .venv
	find . -type d -name "__pycache__" -exec rm -rf {} +
