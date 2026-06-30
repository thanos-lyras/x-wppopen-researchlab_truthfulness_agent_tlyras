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

# Deploy the MCP server to Cloud Run via three sub-steps:
#   1. Ensure the Artifact Registry repo exists.
#   2. Build the image from mcp_server/Dockerfile via Cloud Build (using mcp_server/cloudbuild.yaml).
#   3. Deploy the built image to Cloud Run with --no-allow-unauthenticated (callers
#      must present a bearer token), passing runtime env vars from .env.
# Captures the resulting HTTPS URL and writes MCP_SERVER_URL=<url>/mcp into .env so
# subsequent agent deploys can resolve it.
deploy-mcp:
	@set -a; . $(ENV_FILE); set +a; \
	REPO=cloud-run-source-deploy; \
	IMAGE="$$GOOGLE_CLOUD_LOCATION-docker.pkg.dev/$$GOOGLE_CLOUD_PROJECT/$$REPO/truthfulness-mcp:latest"; \
	echo "▶ Ensuring Artifact Registry repo $$REPO exists in $$GOOGLE_CLOUD_LOCATION..."; \
	gcloud artifacts repositories describe $$REPO --location=$$GOOGLE_CLOUD_LOCATION --project=$$GOOGLE_CLOUD_PROJECT > /dev/null 2>&1 || \
	  gcloud artifacts repositories create $$REPO --repository-format=docker --location=$$GOOGLE_CLOUD_LOCATION --project=$$GOOGLE_CLOUD_PROJECT; \
	echo "▶ Building $$IMAGE via Cloud Build (mcp_server/Dockerfile)..."; \
	gcloud builds submit --project=$$GOOGLE_CLOUD_PROJECT --config mcp_server/cloudbuild.yaml --substitutions _IMAGE_TAG=$$IMAGE . && \
	echo "▶ Deploying to Cloud Run in $$GOOGLE_CLOUD_LOCATION..." && \
	URL=$$(gcloud run deploy truthfulness-mcp \
	    --image "$$IMAGE" \
	    --region "$$GOOGLE_CLOUD_LOCATION" \
	    --project "$$GOOGLE_CLOUD_PROJECT" \
	    --allow-unauthenticated \
	    --set-env-vars "GOOGLE_CLOUD_PROJECT=$$GOOGLE_CLOUD_PROJECT,GOOGLE_CLOUD_LOCATION=$$GOOGLE_CLOUD_LOCATION,GOOGLE_GENAI_USE_VERTEXAI=True,ZERO_SHOT_MODEL=$$ZERO_SHOT_MODEL,EXPLAINER_MODEL=$$EXPLAINER_MODEL,GCS_BUCKET=$$GCS_BUCKET,FINE_TUNED_BASE_MODEL=$$FINE_TUNED_BASE_MODEL,FINE_TUNED_EPOCHS=$$FINE_TUNED_EPOCHS,FINE_TUNED_ADAPTER_SIZE=$$FINE_TUNED_ADAPTER_SIZE,FINE_TUNED_LRM=$$FINE_TUNED_LRM,FINE_TUNED_MODEL=$$FINE_TUNED_MODEL,LAST_TUNING_JOB=$$LAST_TUNING_JOB" \
	    --format='value(status.url)') && \
	echo "✅ Deployed: $$URL" && \
	$(UV) run python -c "from dotenv import set_key; set_key('.env', 'MCP_SERVER_URL', '$$URL/mcp/', quote_mode='never')" && \
	echo "✅ Wrote MCP_SERVER_URL=$$URL/mcp/ to .env"

# Deploy the Explainer agent to Cloud Run (mirrors deploy-mcp's three sub-steps).
# The container exposes `agents.explainer.agent:a2a_app` (a2a-over-HTTP).
# Runtime env vars: MCP_SERVER_URL (so the agent reaches the deployed MCP),
# EXPLAINER_MODEL (model id), and GCP project/location for Vertex.
# Captures the resulting HTTPS URL and writes EXPLAINER_A2A_URL=<url>/.well-known/agent-card.json
# into .env so the orchestrator can discover it.
deploy-explainer:
	@set -a; . $(ENV_FILE); set +a; \
	REPO=cloud-run-source-deploy; \
	IMAGE="$$GOOGLE_CLOUD_LOCATION-docker.pkg.dev/$$GOOGLE_CLOUD_PROJECT/$$REPO/truthfulness-explainer:latest"; \
	echo "▶ Ensuring Artifact Registry repo $$REPO exists in $$GOOGLE_CLOUD_LOCATION..."; \
	gcloud artifacts repositories describe $$REPO --location=$$GOOGLE_CLOUD_LOCATION --project=$$GOOGLE_CLOUD_PROJECT > /dev/null 2>&1 || \
	  gcloud artifacts repositories create $$REPO --repository-format=docker --location=$$GOOGLE_CLOUD_LOCATION --project=$$GOOGLE_CLOUD_PROJECT; \
	echo "▶ Building $$IMAGE via Cloud Build (agents/explainer/Dockerfile)..."; \
	gcloud builds submit --project=$$GOOGLE_CLOUD_PROJECT --config agents/explainer/cloudbuild.yaml --substitutions _IMAGE_TAG=$$IMAGE . && \
	echo "▶ Deploying to Cloud Run in $$GOOGLE_CLOUD_LOCATION..." && \
	PROJECT_NUMBER=$$(gcloud projects describe $$GOOGLE_CLOUD_PROJECT --format='value(projectNumber)') && \
	PUBLIC_HOST="truthfulness-explainer-$$PROJECT_NUMBER.$$GOOGLE_CLOUD_LOCATION.run.app" && \
	URL=$$(gcloud run deploy truthfulness-explainer \
	    --image "$$IMAGE" \
	    --region "$$GOOGLE_CLOUD_LOCATION" \
	    --project "$$GOOGLE_CLOUD_PROJECT" \
	    --allow-unauthenticated \
	    --set-env-vars "GOOGLE_CLOUD_PROJECT=$$GOOGLE_CLOUD_PROJECT,GOOGLE_CLOUD_LOCATION=$$GOOGLE_CLOUD_LOCATION,GOOGLE_GENAI_USE_VERTEXAI=True,MCP_SERVER_URL=$$MCP_SERVER_URL,EXPLAINER_MODEL=$$EXPLAINER_MODEL,EXPLAINER_A2A_PUBLIC_HOST=$$PUBLIC_HOST,EXPLAINER_A2A_PROTOCOL=https,EXPLAINER_A2A_PUBLIC_PORT=443" \
	    --format='value(status.url)') && \
	echo "✅ Deployed: $$URL" && \
	$(UV) run python -c "from dotenv import set_key; set_key('.env', 'EXPLAINER_A2A_URL', '$$URL/.well-known/agent-card.json', quote_mode='never')" && \
	echo "✅ Wrote EXPLAINER_A2A_URL=$$URL/.well-known/agent-card.json to .env"

# Deploy the Zero-shot Predictor agent to Cloud Run (mirrors deploy-explainer).
# The container exposes `agents.zero_shot.agent:a2a_app` (a2a-over-HTTP).
# Writes ZERO_SHOT_A2A_URL=<url>/.well-known/agent-card.json into .env so the
# orchestrator can discover it.
deploy-zero-shot:
	@set -a; . $(ENV_FILE); set +a; \
	REPO=cloud-run-source-deploy; \
	IMAGE="$$GOOGLE_CLOUD_LOCATION-docker.pkg.dev/$$GOOGLE_CLOUD_PROJECT/$$REPO/truthfulness-zero-shot:latest"; \
	echo "▶ Ensuring Artifact Registry repo $$REPO exists in $$GOOGLE_CLOUD_LOCATION..."; \
	gcloud artifacts repositories describe $$REPO --location=$$GOOGLE_CLOUD_LOCATION --project=$$GOOGLE_CLOUD_PROJECT > /dev/null 2>&1 || \
	  gcloud artifacts repositories create $$REPO --repository-format=docker --location=$$GOOGLE_CLOUD_LOCATION --project=$$GOOGLE_CLOUD_PROJECT; \
	echo "▶ Building $$IMAGE via Cloud Build (agents/zero_shot/Dockerfile)..."; \
	gcloud builds submit --project=$$GOOGLE_CLOUD_PROJECT --config agents/zero_shot/cloudbuild.yaml --substitutions _IMAGE_TAG=$$IMAGE . && \
	echo "▶ Deploying to Cloud Run in $$GOOGLE_CLOUD_LOCATION..." && \
	PROJECT_NUMBER=$$(gcloud projects describe $$GOOGLE_CLOUD_PROJECT --format='value(projectNumber)') && \
	PUBLIC_HOST="truthfulness-zero-shot-$$PROJECT_NUMBER.$$GOOGLE_CLOUD_LOCATION.run.app" && \
	URL=$$(gcloud run deploy truthfulness-zero-shot \
	    --image "$$IMAGE" \
	    --region "$$GOOGLE_CLOUD_LOCATION" \
	    --project "$$GOOGLE_CLOUD_PROJECT" \
	    --allow-unauthenticated \
	    --set-env-vars "GOOGLE_CLOUD_PROJECT=$$GOOGLE_CLOUD_PROJECT,GOOGLE_CLOUD_LOCATION=$$GOOGLE_CLOUD_LOCATION,GOOGLE_GENAI_USE_VERTEXAI=True,MCP_SERVER_URL=$$MCP_SERVER_URL,ZERO_SHOT_MODEL=$$ZERO_SHOT_MODEL,ZERO_SHOT_A2A_PUBLIC_HOST=$$PUBLIC_HOST,ZERO_SHOT_A2A_PROTOCOL=https,ZERO_SHOT_A2A_PUBLIC_PORT=443" \
	    --format='value(status.url)') && \
	echo "✅ Deployed: $$URL" && \
	$(UV) run python -c "from dotenv import set_key; set_key('.env', 'ZERO_SHOT_A2A_URL', '$$URL/.well-known/agent-card.json', quote_mode='never')" && \
	echo "✅ Wrote ZERO_SHOT_A2A_URL=$$URL/.well-known/agent-card.json to .env"

# Deploy the Fine-tuned Predictor agent to Cloud Run (mirrors deploy-explainer).
# The container exposes `agents.fine_tuned.agent:a2a_app` (a2a-over-HTTP). The
# fine-tuning-specific env vars (FINE_TUNED_BASE_MODEL, LAST_TUNING_JOB, …) are
# consumed by the MCP server's predict_truthfulness tool — NOT by this agent —
# so they're only injected on `deploy-mcp`, not here.
# Writes FINE_TUNED_A2A_URL=<url>/.well-known/agent-card.json into .env so the
# orchestrator can discover it.
deploy-fine-tuned:
	@set -a; . $(ENV_FILE); set +a; \
	REPO=cloud-run-source-deploy; \
	IMAGE="$$GOOGLE_CLOUD_LOCATION-docker.pkg.dev/$$GOOGLE_CLOUD_PROJECT/$$REPO/truthfulness-fine-tuned:latest"; \
	echo "▶ Ensuring Artifact Registry repo $$REPO exists in $$GOOGLE_CLOUD_LOCATION..."; \
	gcloud artifacts repositories describe $$REPO --location=$$GOOGLE_CLOUD_LOCATION --project=$$GOOGLE_CLOUD_PROJECT > /dev/null 2>&1 || \
	  gcloud artifacts repositories create $$REPO --repository-format=docker --location=$$GOOGLE_CLOUD_LOCATION --project=$$GOOGLE_CLOUD_PROJECT; \
	echo "▶ Building $$IMAGE via Cloud Build (agents/fine_tuned/Dockerfile)..."; \
	gcloud builds submit --project=$$GOOGLE_CLOUD_PROJECT --config agents/fine_tuned/cloudbuild.yaml --substitutions _IMAGE_TAG=$$IMAGE . && \
	echo "▶ Deploying to Cloud Run in $$GOOGLE_CLOUD_LOCATION..." && \
	PROJECT_NUMBER=$$(gcloud projects describe $$GOOGLE_CLOUD_PROJECT --format='value(projectNumber)') && \
	PUBLIC_HOST="truthfulness-fine-tuned-$$PROJECT_NUMBER.$$GOOGLE_CLOUD_LOCATION.run.app" && \
	URL=$$(gcloud run deploy truthfulness-fine-tuned \
	    --image "$$IMAGE" \
	    --region "$$GOOGLE_CLOUD_LOCATION" \
	    --project "$$GOOGLE_CLOUD_PROJECT" \
	    --allow-unauthenticated \
	    --set-env-vars "GOOGLE_CLOUD_PROJECT=$$GOOGLE_CLOUD_PROJECT,GOOGLE_CLOUD_LOCATION=$$GOOGLE_CLOUD_LOCATION,GOOGLE_GENAI_USE_VERTEXAI=True,MCP_SERVER_URL=$$MCP_SERVER_URL,FINE_TUNED_A2A_PUBLIC_HOST=$$PUBLIC_HOST,FINE_TUNED_A2A_PROTOCOL=https,FINE_TUNED_A2A_PUBLIC_PORT=443" \
	    --format='value(status.url)') && \
	echo "✅ Deployed: $$URL" && \
	$(UV) run python -c "from dotenv import set_key; set_key('.env', 'FINE_TUNED_A2A_URL', '$$URL/.well-known/agent-card.json', quote_mode='never')" && \
	echo "✅ Wrote FINE_TUNED_A2A_URL=$$URL/.well-known/agent-card.json to .env"

# Deploy the Orchestrator agent to Cloud Run (mirrors deploy-explainer/-zero-shot/-fine-tuned).
# The container exposes `agents.agent:a2a_app` (a2a-over-HTTP) — same shape as
# the sub-agents. The orchestrator reads the three sub-agents' *_A2A_URL env
# vars to discover them (already in .env from each agent's deploy). It does
# NOT need MCP_SERVER_URL — sub-agents talk to MCP, not the orchestrator.
# Writes ORCHESTRATOR_A2A_URL=<url>/.well-known/agent-card.json into .env.
deploy-orchestrator:
	@set -a; . $(ENV_FILE); set +a; \
	REPO=cloud-run-source-deploy; \
	IMAGE="$$GOOGLE_CLOUD_LOCATION-docker.pkg.dev/$$GOOGLE_CLOUD_PROJECT/$$REPO/truthfulness-orchestrator:latest"; \
	echo "▶ Ensuring Artifact Registry repo $$REPO exists in $$GOOGLE_CLOUD_LOCATION..."; \
	gcloud artifacts repositories describe $$REPO --location=$$GOOGLE_CLOUD_LOCATION --project=$$GOOGLE_CLOUD_PROJECT > /dev/null 2>&1 || \
	  gcloud artifacts repositories create $$REPO --repository-format=docker --location=$$GOOGLE_CLOUD_LOCATION --project=$$GOOGLE_CLOUD_PROJECT; \
	echo "▶ Building $$IMAGE via Cloud Build (agents/Dockerfile)..."; \
	gcloud builds submit --project=$$GOOGLE_CLOUD_PROJECT --config agents/cloudbuild.yaml --substitutions _IMAGE_TAG=$$IMAGE . && \
	echo "▶ Deploying to Cloud Run in $$GOOGLE_CLOUD_LOCATION..." && \
	PROJECT_NUMBER=$$(gcloud projects describe $$GOOGLE_CLOUD_PROJECT --format='value(projectNumber)') && \
	PUBLIC_HOST="truthfulness-orchestrator-$$PROJECT_NUMBER.$$GOOGLE_CLOUD_LOCATION.run.app" && \
	URL=$$(gcloud run deploy truthfulness-orchestrator \
	    --image "$$IMAGE" \
	    --region "$$GOOGLE_CLOUD_LOCATION" \
	    --project "$$GOOGLE_CLOUD_PROJECT" \
	    --allow-unauthenticated \
	    --set-env-vars "GOOGLE_CLOUD_PROJECT=$$GOOGLE_CLOUD_PROJECT,GOOGLE_CLOUD_LOCATION=$$GOOGLE_CLOUD_LOCATION,GOOGLE_GENAI_USE_VERTEXAI=True,ORCHESTRATOR_MODEL=$$ORCHESTRATOR_MODEL,EXPLAINER_A2A_URL=$$EXPLAINER_A2A_URL,FINE_TUNED_A2A_URL=$$FINE_TUNED_A2A_URL,ZERO_SHOT_A2A_URL=$$ZERO_SHOT_A2A_URL,ORCHESTRATOR_A2A_PUBLIC_HOST=$$PUBLIC_HOST,ORCHESTRATOR_A2A_PROTOCOL=https,ORCHESTRATOR_A2A_PUBLIC_PORT=443" \
	    --format='value(status.url)') && \
	echo "✅ Deployed: $$URL" && \
	$(UV) run python -c "from dotenv import set_key; set_key('.env', 'ORCHESTRATOR_A2A_URL', '$$URL/.well-known/agent-card.json', quote_mode='never')" && \
	echo "✅ Wrote ORCHESTRATOR_A2A_URL=$$URL/.well-known/agent-card.json to .env"

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
