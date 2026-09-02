#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${ROOT}"
export SIMULATION_MODE=true
export ALLOW_PRODUCTION_WRITE=false
export AGENTTEAMS_ENABLED=false
export AGENTTEAMS_LIVE_REQUIRED=false
export ENERGYMESH_HOST=127.0.0.1
export ENERGYMESH_PORT=8000
export ENERGYMESH_DB_PATH="${ROOT}/var/energymesh.db"
export ENERGYMESH_EVIDENCE_DIR="${ROOT}/runs"
mkdir -p var runs
echo "Starting EnergyMesh (standalone, no AgentTeams Matrix)..."
exec .venv/bin/uvicorn energymesh.api:app --app-dir src --host 127.0.0.1 --port 8000 --reload
