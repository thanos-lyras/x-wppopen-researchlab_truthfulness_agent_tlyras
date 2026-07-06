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

# One-time (idempotent) bootstrap of the orchestrator in the shared A2A Gateway:
#   1. Mint the per-agent bearer token in Secret Manager + grant the gateway SA read.
#   2. Upload the per-agent JSON config to gs://<project>-a2a-gateway-agent-config/agents/.
# Requires `make deploy-orchestrator` to have run first (so ORCHESTRATOR_A2A_URL is in .env).
# Prints the fresh token once — copy into the team vault AND paste into .env as
# A2A_GATEWAY_TRUTHFULNESS_ORCHESTRATOR_BEARER_TOKEN before running `make smoke-orchestrator-gateway`.
register-orchestrator-gateway:
	@set -a; source $(ENV_FILE); set +a; \
	if [ -z "$$GOOGLE_CLOUD_PROJECT" ]; then echo "❌ GOOGLE_CLOUD_PROJECT missing in $(ENV_FILE)"; exit 1; fi; \
	if [ -z "$$ORCHESTRATOR_A2A_URL" ]; then echo "❌ ORCHESTRATOR_A2A_URL missing — run 'make deploy-orchestrator' first"; exit 1; fi; \
	UPSTREAM_BASE_URL=$${ORCHESTRATOR_A2A_URL%/.well-known/agent-card.json}; \
	BUCKET=$${GOOGLE_CLOUD_PROJECT}-a2a-gateway-agent-config; \
	echo "▶ Minting bearer token in Secret Manager..."; \
	$(UV) run python scripts/gateway/upsert_gateway_bearer_secret.py \
		--project $$GOOGLE_CLOUD_PROJECT \
		--secret-id a2a-gateway-truthfulness-orchestrator-bearer-token \
		--grant-accessor-service-account a2a-agent-gateway@x-wppai-dataspine-choreo-dev.iam.gserviceaccount.com \
		--print-token; \
	echo ""; \
	echo "▶ Uploading per-agent config to gs://$$BUCKET/agents/truthfulness-orchestrator.json..."; \
	$(UV) run python scripts/gateway/upsert_gcs_agent_config.py \
		--project $$GOOGLE_CLOUD_PROJECT \
		--bucket $$BUCKET \
		--prefix agents \
		--agent-id truthfulness-orchestrator \
		--backend-kind http_jsonrpc \
		--upstream-base-url $$UPSTREAM_BASE_URL \
		--name "Truthfulness Orchestrator" \
		--description "ADK 2.0 orchestrator classifying statements as truthful/untruthful via zero-shot, fine-tuned, and explainer sub-agents." \
		--monthly-budget-usd 50 \
		--estimated-cost-per-call-usd 0.05 \
		--capture-call-content \
		--capture-call-content-max-chars 4000 \
		--forward-id-token

# Re-upload the per-agent GCS config WITHOUT rotating the bearer token.
# Use this when the orchestrator URL changes (e.g. after a region move or
# service rename) so the gateway learns the new `upstream_base_url` while
# the existing token in .env keeps working.
update-orchestrator-gateway-config:
	@set -a; source $(ENV_FILE); set +a; \
	if [ -z "$$GOOGLE_CLOUD_PROJECT" ]; then echo "❌ GOOGLE_CLOUD_PROJECT missing in $(ENV_FILE)"; exit 1; fi; \
	if [ -z "$$ORCHESTRATOR_A2A_URL" ]; then echo "❌ ORCHESTRATOR_A2A_URL missing — run 'make deploy-orchestrator' first"; exit 1; fi; \
	UPSTREAM_BASE_URL=$${ORCHESTRATOR_A2A_URL%/.well-known/agent-card.json}; \
	BUCKET=$${GOOGLE_CLOUD_PROJECT}-a2a-gateway-agent-config; \
	echo "▶ Updating gs://$$BUCKET/agents/truthfulness-orchestrator.json → upstream $$UPSTREAM_BASE_URL"; \
	$(UV) run python scripts/gateway/upsert_gcs_agent_config.py \
		--project $$GOOGLE_CLOUD_PROJECT \
		--bucket $$BUCKET \
		--prefix agents \
		--agent-id truthfulness-orchestrator \
		--backend-kind http_jsonrpc \
		--upstream-base-url $$UPSTREAM_BASE_URL \
		--name "Truthfulness Orchestrator" \
		--description "ADK 2.0 orchestrator classifying statements as truthful/untruthful via zero-shot, fine-tuned, and explainer sub-agents." \
		--monthly-budget-usd 50 \
		--estimated-cost-per-call-usd 0.05 \
		--capture-call-content \
		--capture-call-content-max-chars 4000 \
		--forward-id-token

# End-to-end smoke test through the A2A Gateway. Requires:
#   - `make register-orchestrator-gateway` completed
#   - A2A_GATEWAY_BASE_URL, A2A_GATEWAY_AGENT_ID,
#     A2A_GATEWAY_TRUTHFULNESS_ORCHESTRATOR_BEARER_TOKEN, A2A_CALLER_EMAIL set in .env
smoke-orchestrator-gateway:
	PYTHONPATH=. $(UV) run --env-file $(ENV_FILE) python scripts/gateway/smoke_orchestrator.py

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

# Same as `dev` but no browser UI — orchestrator A2A on :8000 takes the slot
# instead, so you can curl the orchestrator directly:
#   curl -sS -X POST http://localhost:8000/ ...
dev-no-ui:
	$(MAKE) -j 5 run-mcp run-a2a-zero-shot run-a2a-fine-tuned run-a2a-explainer run-a2a-orchestrator

# Cleanup the venv and Python caches
clean:
	rm -rf .venv
	find . -type d -name "__pycache__" -exec rm -rf {} +
