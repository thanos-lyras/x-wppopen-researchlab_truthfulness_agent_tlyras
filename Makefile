SHELL := /bin/bash
UV := uv
ENV_FILE := .env

.DEFAULT_GOAL := help

.PHONY: help \
        bootstrap configure install auth \
        run-web run-mcp run-a2a \
        _run-a2a-zero-shot _run-a2a-fine-tuned _run-a2a-explainer \
        dev \
        tf-init tf-apply tf-destroy \
        deploy-all sync-tuned-endpoint \
        register-orchestrator-gateway smoke-orchestrator-gateway \
        ask \
        clean

# ── Help ───────────────────────────────────────────────────────────────
help:
	@echo "truthfulness-agent — make targets"
	@echo ""
	@echo "Setup (first-time):"
	@echo "  bootstrap                            configure + install + auth"
	@echo ""
	@echo "Local dev:"
	@echo "  dev                                  all services + browser UI on :8080"
	@echo "  run-mcp                              MCP server only"
	@echo "  run-a2a NAME=<agent>                 expose one agent as A2A"
	@echo "  run-web                              browser playground on :8080"
	@echo ""
	@echo "Deploy:"
	@echo "  tf-init                              terraform init"
	@echo "  tf-apply                             terraform apply — full bootstrap"
	@echo "  tf-destroy                           terraform destroy"
	@echo "  deploy-all                           bypass terraform: deploy 5 services + register-gateway"
	@echo "  sync-tuned-endpoint                  push FINE_TUNED_MODEL from .env to deployed MCP (~60s, no rebuild)"
	@echo ""
	@echo "Gateway:"
	@echo "  register-orchestrator-gateway        reuse or mint bearer, upload config, write .env"
	@echo "  smoke-orchestrator-gateway           end-to-end smoke via gateway"
	@echo ""
	@echo "Invoke:"
	@echo "  ask PROMPT=\"<text>\" [FILE=<path>|URI=<gs://...>] [AGENT=<name>]"
	@echo ""
	@echo "Housekeeping:"
	@echo "  clean                                remove .venv + __pycache__"

# ── Setup ──────────────────────────────────────────────────────────────
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

# ── Local dev ──────────────────────────────────────────────────────────
run-web:
	PYTHONPATH=. $(UV) run --env-file $(ENV_FILE) adk web --reload_agents --port 8080 agents

run-mcp:
	@set -a; source $(ENV_FILE); set +a; \
	if [ -z "$$MCP_SERVER_PORT" ]; then echo "❌ MCP_SERVER_PORT is not set in $(ENV_FILE)"; exit 1; fi; \
	PYTHONPATH=. $(UV) run --env-file $(ENV_FILE) uvicorn mcp_server.server:app --host 0.0.0.0 --port $$MCP_SERVER_PORT --reload

NAME ?= zero_shot
run-a2a:
	@set -a; source $(ENV_FILE); set +a; \
	PORT_VAR=$$(echo $(NAME) | tr a-z A-Z)_A2A_PORT; \
	PORT=$${!PORT_VAR}; \
	if [ -z "$$PORT" ]; then echo "❌ $$PORT_VAR is not set in $(ENV_FILE)"; exit 1; fi; \
	if [ "$(NAME)" = "orchestrator" ]; then MODULE=agents.agent:a2a_app; else MODULE=agents.$(NAME).agent:a2a_app; fi; \
	PYTHONPATH=. $(UV) run --env-file $(ENV_FILE) uvicorn $$MODULE --host 0.0.0.0 --port $$PORT --reload

# Internal wrappers — `make -j` can't call `run-a2a` twice with different NAME=.
_run-a2a-zero-shot:    ; @$(MAKE) run-a2a NAME=zero_shot
_run-a2a-fine-tuned:   ; @$(MAKE) run-a2a NAME=fine_tuned
_run-a2a-explainer:    ; @$(MAKE) run-a2a NAME=explainer

dev:
	@$(MAKE) -j 5 run-mcp _run-a2a-zero-shot _run-a2a-fine-tuned _run-a2a-explainer run-web

# ── Deploy ─────────────────────────────────────────────────────────────
tf-init:             ; cd terraform && terraform init
tf-apply:            ; cd terraform && terraform apply
tf-destroy:          ; cd terraform && terraform destroy
deploy-all:          ; PYTHONPATH=. $(UV) run python deployment/deploy.py all
sync-tuned-endpoint: ; PYTHONPATH=. $(UV) run --env-file $(ENV_FILE) python deployment/deploy.py sync-tuned-endpoint

# ── Gateway ────────────────────────────────────────────────────────────
register-orchestrator-gateway: ; PYTHONPATH=. $(UV) run python deployment/deploy.py register-gateway
smoke-orchestrator-gateway:    ; PYTHONPATH=. $(UV) run python deployment/deploy.py smoke-gateway

# ── Invoke ─────────────────────────────────────────────────────────────
ask:
	@if [ -z "$(PROMPT)" ]; then \
		echo "❌ PROMPT=\"<text>\" is required."; \
		echo "   Optional: FILE=<path> or URI=<gs://...>, AGENT=<zero_shot|fine_tuned|explainer>"; \
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
