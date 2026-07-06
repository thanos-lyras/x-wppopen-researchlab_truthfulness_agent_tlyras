SHELL := /bin/bash
UV := uv
ENV_FILE := .env

# Constants for the A2A Gateway registration flow (see README § Security).
GATEWAY_SA        := a2a-agent-gateway@x-wppai-dataspine-choreo-dev.iam.gserviceaccount.com
GATEWAY_SECRET_ID := a2a-gateway-truthfulness-orchestrator-bearer-token
GATEWAY_AGENT_ID  := truthfulness-orchestrator
GATEWAY_DESC      := ADK 2.0 orchestrator classifying statements as truthful/untruthful via zero-shot, fine-tuned, and explainer sub-agents.

.DEFAULT_GOAL := help

.PHONY: help bootstrap configure install auth notebook \
        split finetune sync-tuned-model test-fine-tuned \
        run-web run-mcp run-a2a \
        _run-a2a-zero-shot _run-a2a-fine-tuned _run-a2a-explainer _run-a2a-orchestrator \
        dev dev-no-ui \
        deploy-mcp deploy-zero-shot deploy-fine-tuned deploy-explainer deploy-orchestrator deploy-all \
        register-orchestrator-gateway update-orchestrator-gateway-config smoke-orchestrator-gateway \
        clean

# ── Help ───────────────────────────────────────────────────────────────
help:
	@echo "truthfulness-agent — make targets"
	@echo ""
	@echo "Setup (first-time):"
	@echo "  bootstrap                            configure + install + auth in one go"
	@echo "  configure                            copy .env.example → .env (if missing)"
	@echo "  install                              uv sync (base deps)"
	@echo "  auth                                 gcloud application-default login"
	@echo "  notebook                             install extras + launch JupyterLab"
	@echo ""
	@echo "Local dev:"
	@echo "  dev                                  all 5 services + browser UI on :8080"
	@echo "  dev-no-ui                            all 5 A2A services (orchestrator on :8000)"
	@echo "  run-mcp                              MCP server only"
	@echo "  run-a2a NAME=<agent>                 expose one agent as A2A (uvicorn)"
	@echo "  run-web                              browser playground on :8080"
	@echo ""
	@echo "Cloud deploys (deployment/deploy.py):"
	@echo "  deploy-all                           deploy all 5 in dependency order"
	@echo "  deploy-{mcp,zero-shot,fine-tuned,explainer,orchestrator}"
	@echo ""
	@echo "Gateway integration (see README § Security):"
	@echo "  register-orchestrator-gateway        one-time: mint bearer + upload config"
	@echo "  update-orchestrator-gateway-config   re-upload config without rotating token"
	@echo "  smoke-orchestrator-gateway           end-to-end smoke via gateway"
	@echo ""
	@echo "Fine-tuning (Vertex SFT):"
	@echo "  split                                write dataset splits (no SFT)"
	@echo "  finetune                             split + upload to GCS + submit + wait"
	@echo "  sync-tuned-model JOB=…               poll a submitted job"
	@echo "  test-fine-tuned                      smoke-test the tuned MCP tool"
	@echo ""
	@echo "Housekeeping:"
	@echo "  clean                                remove .venv + __pycache__"

# ── Setup ──────────────────────────────────────────────────────────────
# First-time onboarding: everything a new dev needs in one command.
bootstrap: configure install auth

configure:
	@if [ ! -f $(ENV_FILE) ]; then \
		cp .env.example $(ENV_FILE); \
		echo "Created $(ENV_FILE) from .env.example. Please UPDATE it."; \
	fi

install:
	$(UV) sync

auth:
	gcloud auth application-default login

notebook:
	$(UV) sync --extra notebook
	$(UV) run --extra notebook jupyter lab notebooks/

# ── Fine-tuning (Vertex SFT) ───────────────────────────────────────────
split:
	PYTHONPATH=. $(UV) run --env-file $(ENV_FILE) python -m scripts.finetune --split-only

# Full SFT: split → GCS upload → submit → poll → write FINE_TUNED_MODEL to .env.
# Job runs 30-90 min, a few dollars. Requires GCS_BUCKET in .env.
finetune:
	PYTHONPATH=. $(UV) run --env-file $(ENV_FILE) python -m scripts.finetune

# Poll a submitted job (used after `python -m scripts.finetune --no-wait`).
# Usage: make sync-tuned-model JOB=projects/.../tuningJobs/<id>
sync-tuned-model:
	@if [ -z "$(JOB)" ]; then echo "❌ JOB=projects/.../tuningJobs/<id> required"; exit 1; fi
	PYTHONPATH=. $(UV) run --env-file $(ENV_FILE) python -m scripts.sync_tuned_model $(JOB)

# Smoke test the predict_truthfulness MCP tool with use_fine_tuned=True.
# Requires `make run-mcp` in another terminal.
test-fine-tuned:
	PYTHONPATH=. $(UV) run --env-file $(ENV_FILE) python -m scripts.test_predict_fine_tuned

# ── Local dev ──────────────────────────────────────────────────────────
# Browser playground for the whole orchestrator + sub-agents on :8080.
run-web:
	PYTHONPATH=. $(UV) run --env-file $(ENV_FILE) adk web --reload_agents --port 8080 agents

# MCP tool server on http://127.0.0.1:$MCP_SERVER_PORT/mcp.
run-mcp:
	@set -a; source $(ENV_FILE); set +a; \
	if [ -z "$$MCP_SERVER_PORT" ]; then echo "❌ MCP_SERVER_PORT is not set in $(ENV_FILE)"; exit 1; fi; \
	echo "▶ MCP tool server on port $$MCP_SERVER_PORT (endpoint /mcp)"; \
	PYTHONPATH=. $(UV) run --env-file $(ENV_FILE) uvicorn mcp_server.server:app --host 0.0.0.0 --port $$MCP_SERVER_PORT --reload

# Expose an agent as an A2A service: `make run-a2a NAME=zero_shot`
# Port from <NAME_UPPER>_A2A_PORT in .env. NAME=orchestrator → agents.agent (lives directly in agents/).
NAME ?= zero_shot
run-a2a:
	@set -a; source $(ENV_FILE); set +a; \
	PORT_VAR=$$(echo $(NAME) | tr a-z A-Z)_A2A_PORT; \
	PORT=$${!PORT_VAR}; \
	if [ -z "$$PORT" ]; then echo "❌ $$PORT_VAR is not set in $(ENV_FILE)"; exit 1; fi; \
	if [ "$(NAME)" = "orchestrator" ]; then MODULE=agents.agent:a2a_app; else MODULE=agents.$(NAME).agent:a2a_app; fi; \
	echo "▶ Exposing $(NAME) on port $$PORT (from $$PORT_VAR, module $$MODULE)"; \
	PYTHONPATH=. $(UV) run --env-file $(ENV_FILE) uvicorn $$MODULE --host 0.0.0.0 --port $$PORT --reload

# Internal wrappers (leading _). `make -j` can't call `run-a2a` twice with
# different NAME= args, so `dev` / `dev-no-ui` need one target per agent.
# You should not call these directly — use `dev` or `run-a2a NAME=<x>`.
_run-a2a-zero-shot:    ; @$(MAKE) run-a2a NAME=zero_shot
_run-a2a-fine-tuned:   ; @$(MAKE) run-a2a NAME=fine_tuned
_run-a2a-explainer:    ; @$(MAKE) run-a2a NAME=explainer
_run-a2a-orchestrator: ; @$(MAKE) run-a2a NAME=orchestrator

# Full local stack: MCP + 3 sub-agent A2A backends + browser UI on :8080.
# The orchestrator runs in-process inside `adk web`. To also expose the
# orchestrator's A2A endpoint (for curl), run `dev-no-ui` instead.
dev:
	@$(MAKE) -j 5 run-mcp _run-a2a-zero-shot _run-a2a-fine-tuned _run-a2a-explainer run-web

# Same as `dev` but the orchestrator A2A endpoint on :8000 replaces the browser UI.
dev-no-ui:
	@$(MAKE) -j 5 run-mcp _run-a2a-zero-shot _run-a2a-fine-tuned _run-a2a-explainer _run-a2a-orchestrator

# ── Cloud deploys ──────────────────────────────────────────────────────
# The full deploy logic (Artifact Registry probe, Cloud Build, gcloud run deploy
# with ingress + vpc-egress + IAM grants, .env write-back) lives in
# deployment/deploy.py. Targets here are one-liners. See README § Cloud deployment.
deploy-mcp:          ; $(UV) run python deployment/deploy.py mcp
deploy-zero-shot:    ; $(UV) run python deployment/deploy.py zero-shot
deploy-fine-tuned:   ; $(UV) run python deployment/deploy.py fine-tuned
deploy-explainer:    ; $(UV) run python deployment/deploy.py explainer
deploy-orchestrator: ; $(UV) run python deployment/deploy.py orchestrator
deploy-all:          ; $(UV) run python deployment/deploy.py all

# ── A2A Agents Gateway (external bearer-token access) ──────────────────
# One-time bootstrap: mints the bearer in Secret Manager, grants the gateway SA
# access, uploads the per-agent JSON config to GCS. Prints the token — capture
# it into your team vault AND paste into .env as
# A2A_GATEWAY_TRUTHFULNESS_ORCHESTRATOR_BEARER_TOKEN.
register-orchestrator-gateway:
	@set -a; source $(ENV_FILE); set +a; \
	if [ -z "$$GOOGLE_CLOUD_PROJECT" ]; then echo "❌ GOOGLE_CLOUD_PROJECT missing in $(ENV_FILE)"; exit 1; fi; \
	if [ -z "$$ORCHESTRATOR_A2A_URL" ]; then echo "❌ ORCHESTRATOR_A2A_URL missing — run 'make deploy-orchestrator' first"; exit 1; fi; \
	UPSTREAM=$${ORCHESTRATOR_A2A_URL%/.well-known/agent-card.json}; \
	BUCKET=$${GOOGLE_CLOUD_PROJECT}-a2a-gateway-agent-config; \
	echo "▶ Minting bearer token in Secret Manager..."; \
	$(UV) run python scripts/gateway/upsert_gateway_bearer_secret.py \
		--project $$GOOGLE_CLOUD_PROJECT \
		--secret-id $(GATEWAY_SECRET_ID) \
		--grant-accessor-service-account $(GATEWAY_SA) \
		--print-token; \
	echo ""; \
	echo "▶ Uploading gs://$$BUCKET/agents/$(GATEWAY_AGENT_ID).json → upstream $$UPSTREAM"; \
	$(UV) run python scripts/gateway/upsert_gcs_agent_config.py \
		--project $$GOOGLE_CLOUD_PROJECT --bucket $$BUCKET --prefix agents \
		--agent-id $(GATEWAY_AGENT_ID) --backend-kind http_jsonrpc \
		--upstream-base-url $$UPSTREAM \
		--name "Truthfulness Orchestrator" \
		--description "$(GATEWAY_DESC)" \
		--monthly-budget-usd 50 --estimated-cost-per-call-usd 0.05 \
		--capture-call-content --capture-call-content-max-chars 4000 \
		--forward-id-token

# Re-upload the GCS config WITHOUT rotating the bearer token. Use after any
# change to the orchestrator's URL (region move, service rename).
update-orchestrator-gateway-config:
	@set -a; source $(ENV_FILE); set +a; \
	if [ -z "$$GOOGLE_CLOUD_PROJECT" ]; then echo "❌ GOOGLE_CLOUD_PROJECT missing in $(ENV_FILE)"; exit 1; fi; \
	if [ -z "$$ORCHESTRATOR_A2A_URL" ]; then echo "❌ ORCHESTRATOR_A2A_URL missing — run 'make deploy-orchestrator' first"; exit 1; fi; \
	UPSTREAM=$${ORCHESTRATOR_A2A_URL%/.well-known/agent-card.json}; \
	BUCKET=$${GOOGLE_CLOUD_PROJECT}-a2a-gateway-agent-config; \
	echo "▶ Updating gs://$$BUCKET/agents/$(GATEWAY_AGENT_ID).json → upstream $$UPSTREAM"; \
	$(UV) run python scripts/gateway/upsert_gcs_agent_config.py \
		--project $$GOOGLE_CLOUD_PROJECT --bucket $$BUCKET --prefix agents \
		--agent-id $(GATEWAY_AGENT_ID) --backend-kind http_jsonrpc \
		--upstream-base-url $$UPSTREAM \
		--name "Truthfulness Orchestrator" \
		--description "$(GATEWAY_DESC)" \
		--monthly-budget-usd 50 --estimated-cost-per-call-usd 0.05 \
		--capture-call-content --capture-call-content-max-chars 4000 \
		--forward-id-token

# End-to-end smoke via the gateway. Requires the four A2A_GATEWAY_* vars in .env
# (see .env.example) — token from `make register-orchestrator-gateway`.
smoke-orchestrator-gateway:
	PYTHONPATH=. $(UV) run --env-file $(ENV_FILE) python scripts/gateway/smoke_orchestrator.py

# ── Housekeeping ───────────────────────────────────────────────────────
clean:
	rm -rf .venv
	find . -type d -name "__pycache__" -exec rm -rf {} +
