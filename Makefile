SHELL := /bin/bash
UV := uv
ENV_FILE := .env

.DEFAULT_GOAL := help

.PHONY: help bootstrap bootstrap-bucket configure install auth notebook \
        split finetune sync-tuned-model test-fine-tuned \
        run-web run-mcp run-a2a \
        _run-a2a-zero-shot _run-a2a-fine-tuned _run-a2a-explainer _run-a2a-orchestrator \
        dev dev-no-ui \
        deploy-mcp deploy-zero-shot deploy-fine-tuned deploy-explainer deploy-orchestrator deploy-all \
        tf-init tf-plan tf-apply tf-destroy \
        register-orchestrator-gateway update-orchestrator-gateway-config smoke-orchestrator-gateway \
        ask test-ask test-ask-inline test-ask-file test-ask-uri test-ask-agent-hint test-ask-raw \
        clean

# ── Help ───────────────────────────────────────────────────────────────
help:
	@echo "truthfulness-agent — make targets"
	@echo ""
	@echo "Setup (first-time):"
	@echo "  bootstrap                            configure + install + auth + bootstrap-bucket"
	@echo "  configure                            copy .env.example → .env (if missing)"
	@echo "  install                              uv sync (base deps)"
	@echo "  auth                                 gcloud application-default login"
	@echo "  bootstrap-bucket                     idempotently create GCS bucket + grant runtime SA object access"
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
	@echo "Terraform (terraform/):"
	@echo "  tf-init                              terraform init"
	@echo "  tf-plan                              terraform plan"
	@echo "  tf-apply                             terraform apply — provisions bucket + AR + PGA then runs deploy-all"
	@echo "  tf-destroy                           terraform destroy (does NOT undeploy Cloud Run services created by deploy.py)"
	@echo ""
	@echo "Gateway integration (see README § Security):"
	@echo "  register-orchestrator-gateway        one-time: mint bearer + upload config"
	@echo "  update-orchestrator-gateway-config   re-upload config without rotating token"
	@echo "  smoke-orchestrator-gateway           end-to-end smoke via gateway"
	@echo ""
	@echo "Ask the deployed system (see main.py --help for all options):"
	@echo "  ask PROMPT=\"<text>\"                   inline prompt, no file"
	@echo "  ask PROMPT=\"<text>\" FILE=<local>      upload local file + prompt"
	@echo "  ask PROMPT=\"<text>\" URI=<gs://...>    use pre-uploaded GCS file + prompt"
	@echo "  ask PROMPT=\"<text>\" AGENT=<name>      routing hint: zero_shot | fine_tuned | explainer"
	@echo ""
	@echo "Manual test scenarios for main.py:"
	@echo "  test-ask-inline                      inline PROMPT, no file (sub-agent will ask for URI)"
	@echo "  test-ask-file                        golden path: PROMPT + FILE upload → real verdict"
	@echo "  test-ask-uri                         upload fixture then PROMPT + URI (skips ad-hoc upload)"
	@echo "  test-ask-agent-hint                  PROMPT + FILE + AGENT=fine_tuned routing hint"
	@echo "  test-ask-raw                         golden path with --raw (prints full JSON envelope)"
	@echo "  test-ask                             run test-ask-inline + test-ask-file + test-ask-uri + test-ask-agent-hint in sequence"
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
# Depends on ADC being available for bootstrap-bucket → run `auth` first.
bootstrap: configure install auth bootstrap-bucket

configure:
	@if [ ! -f $(ENV_FILE) ]; then \
		cp .env.example $(ENV_FILE); \
		echo "Created $(ENV_FILE) from .env.example. Please UPDATE it."; \
	fi

install:
	$(UV) sync

auth:
	gcloud auth application-default login

# Idempotently create the GCS upload bucket + grant the runtime compute SA
# `roles/storage.objectAdmin` on it. Reads GCS_BUCKET/GCS_LOCATION/PROJECT
# from .env. Runs no-op when everything already exists.
bootstrap-bucket:
	PYTHONPATH=. $(UV) run python deployment/bootstrap_bucket.py

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
deploy-mcp:          ; PYTHONPATH=. $(UV) run python deployment/deploy.py mcp
deploy-zero-shot:    ; PYTHONPATH=. $(UV) run python deployment/deploy.py zero-shot
deploy-fine-tuned:   ; PYTHONPATH=. $(UV) run python deployment/deploy.py fine-tuned
deploy-explainer:    ; PYTHONPATH=. $(UV) run python deployment/deploy.py explainer
deploy-orchestrator: ; PYTHONPATH=. $(UV) run python deployment/deploy.py orchestrator
deploy-all:          ; PYTHONPATH=. $(UV) run python deployment/deploy.py all

# ── Terraform ──────────────────────────────────────────────────────────
# Declarative wrapper: provisions bucket + Artifact Registry + PGA on the
# default subnet, then invokes `deployment/deploy.py all` via a null_resource
# so all 5 Cloud Run services come up in one `terraform apply`. See terraform/.
tf-init:    ; cd terraform && terraform init
tf-plan:    ; cd terraform && terraform plan
tf-apply:   ; cd terraform && terraform apply
tf-destroy: ; cd terraform && terraform destroy

# ── A2A Agents Gateway (external bearer-token access) ──────────────────
# All three targets are thin wrappers around subcommands of deployment/deploy.py.
# The argument surface + gateway constants live in that one place — see
# deployment/deploy.py `register_gateway` / `update_gateway_config` / `smoke_gateway`.
register-orchestrator-gateway:        ; PYTHONPATH=. $(UV) run python deployment/deploy.py register-gateway
update-orchestrator-gateway-config:   ; PYTHONPATH=. $(UV) run python deployment/deploy.py update-gateway-config
smoke-orchestrator-gateway:           ; PYTHONPATH=. $(UV) run python deployment/deploy.py smoke-gateway

# ── Ask the deployed system (CLI client) ───────────────────────────────
# Thin wrapper around `python main.py` — see main.py --help for full docs.
# PROMPT is required (agents are instructed via natural language). FILE and
# URI are optional data sources — mutually exclusive; PROMPT alone is fine.
#   Usage:
#     make ask PROMPT="Classify: The Earth is flat."
#     make ask PROMPT="please classify and explain" FILE=data/sample_1.json
#     make ask PROMPT="please classify" URI=gs://bucket/uploads/mine.json
#     make ask PROMPT="use fine-tuned" FILE=data/sample_3.json AGENT=fine_tuned
ask:
	@if [ -z "$(PROMPT)" ]; then \
		echo "❌ PROMPT=\"<text>\" is required."; \
		echo "   Optional: FILE=<path> or URI=<gs://...> (data source)."; \
		echo "   Optional: AGENT=<zero_shot|fine_tuned|explainer> (routing hint)."; \
		echo "   See: python main.py --help"; \
		exit 1; \
	fi
	PYTHONPATH=. $(UV) run --env-file $(ENV_FILE) python main.py \
		--prompt "$(PROMPT)" \
		$(if $(FILE),--file "$(FILE)") \
		$(if $(URI),--uri "$(URI)") \
		$(if $(AGENT),--agent "$(AGENT)")

# ── Housekeeping ───────────────────────────────────────────────────────
clean:
	rm -rf .venv
	find . -type d -name "__pycache__" -exec rm -rf {} +
