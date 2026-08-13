.PHONY: install format lint typecheck test run agentteams-resources verify

install:
	python3 -m pip install -e ".[dev]"

format:
	python3 -m ruff format src tests
	python3 -m ruff check --fix src tests

lint:
	python3 -m ruff format --check src tests
	python3 -m ruff check src tests

typecheck:
	python3 -m mypy src

test:
	python3 -m pytest

run:
	set -a; [ ! -f .env ] || . ./.env; set +a; python3 -m uvicorn energymesh.api:app --app-dir src --reload

agentteams-resources:
	@printf "%s\n" "Apply agentteams/agentteams-resources.yaml with the open-source agentscope-ai/AgentTeams controller after installing its quickstart runtime."

verify: lint typecheck test
