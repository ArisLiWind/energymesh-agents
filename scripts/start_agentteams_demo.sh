#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ENV_FILE="${ENV_FILE:-${ROOT}/.env.agentteams.local}"
CODESPACE_NAME="${CODESPACE_NAME:-energymesh-agentteams-min-q7746qqwx77qcv45}"
ENERGYMESH_PORT="${ENERGYMESH_PORT:-8000}"
LOG_DIR="${ROOT}/runs"
PYTHON_BIN="${PYTHON_BIN:-${ROOT}/.venv/bin/python}"
mkdir -p "${LOG_DIR}"

cd "${ROOT}"

if [[ ! -f "${ENV_FILE}" ]]; then
  cat <<MSG
FAIL: ${ENV_FILE} does not exist.

Create it with:
  python3 scripts/local_agentteams_secret_form.py

Minimum required values:
  AGENTTEAMS_RUNTIME_MODE=remote_matrix
  AGENTTEAMS_TEAM_NAME=energymesh-demo
  AGENTTEAMS_TEAM_ROOM_ID=<Team Room ID>
  AGENTTEAMS_MATRIX_BASE_URL=http://127.0.0.1:18080
  AGENTTEAMS_MATRIX_ACCESS_TOKEN=<Matrix access token>
  AGENTTEAMS_MANAGER_USER_ID=@energymesh-team-leader:matrix-local.agentteams.io:18080
  AGENTTEAMS_REMOTE_WORKERS=energymesh-team-leader,perception-worker,dispatch-worker,audit-worker,execution-worker
  AGENTTEAMS_LLM_PROVIDER=openai-compat
  AGENTTEAMS_OPENAI_BASE_URL=https://api.deepseek.com/v1
  AGENTTEAMS_DEFAULT_MODEL=deepseek-chat
  AGENTTEAMS_LLM_API_KEY=<DeepSeek API key>
MSG
  exit 2
fi

set -a
# shellcheck disable=SC1090
source "${ENV_FILE}"
set +a

export SIMULATION_MODE=true
export ALLOW_PRODUCTION_WRITE=false
export AGENTTEAMS_ENABLED="${AGENTTEAMS_ENABLED:-true}"
export AGENTTEAMS_LIVE_REQUIRED="${AGENTTEAMS_LIVE_REQUIRED:-true}"
export AGENTTEAMS_RUNTIME_MODE="${AGENTTEAMS_RUNTIME_MODE:-remote_matrix}"
export AGENTTEAMS_TEAM_NAME="${AGENTTEAMS_TEAM_NAME:-energymesh-park-control}"
export AGENTTEAMS_MANAGER_USER_ID="${AGENTTEAMS_MANAGER_USER_ID:-@energymesh-team-leader:matrix-local.agentteams.io:18080}"
export AGENTTEAMS_REMOTE_WORKERS="${AGENTTEAMS_REMOTE_WORKERS:-energymesh-team-leader,perception-worker,dispatch-worker,audit-worker,execution-worker}"
export AGENTTEAMS_MATRIX_BASE_URL="${AGENTTEAMS_MATRIX_BASE_URL:-http://127.0.0.1:18080}"
export ENERGYMESH_HOST=127.0.0.1
export ENERGYMESH_PORT

need_gh=false
if ! curl -fsS "${AGENTTEAMS_MATRIX_BASE_URL}/_matrix/client/versions" >/dev/null 2>&1; then
  need_gh=true
fi

if [[ "${need_gh}" == "true" ]]; then
  if ! command -v gh >/dev/null 2>&1; then
    echo "FAIL: Matrix is unreachable and gh CLI is not available for Codespaces forwarding."
    exit 2
  fi
  echo "Starting Codespace ${CODESPACE_NAME} if needed..."
  gh codespace ssh -c "${CODESPACE_NAME}" -- true
  echo "Checking AgentTeams containers in Codespace..."
  gh codespace ssh -c "${CODESPACE_NAME}" -- \
    'docker ps --format "{{.Names}} {{.Status}}" | grep agentteams || true'
  echo "Checking AgentTeams workers and teams..."
  gh codespace ssh -c "${CODESPACE_NAME}" -- \
    'docker exec agentteams-controller agt get workers; docker exec agentteams-controller agt get teams || true'
  gh codespace ssh -c "${CODESPACE_NAME}" -- \
    'teams="$(docker exec agentteams-controller agt get teams || true)"
workers="$(docker exec agentteams-controller agt get workers || true)"
echo "$teams" | grep -q Failed && { echo "FAIL: AgentTeams Team is Failed."; echo "$teams"; exit 2; }
echo "$workers" | grep -Eq "Running|Ready|Active" || { echo "FAIL: no AgentTeams Worker is Running/Ready/Active."; echo "$workers"; exit 2; }'
  echo "Checking Codespace AgentTeams Matrix/Element ports..."
  gh codespace ssh -c "${CODESPACE_NAME}" -- \
    'for i in $(seq 1 45); do curl -fsS http://127.0.0.1:18080/_matrix/client/versions >/dev/null 2>&1 && curl -fsSI http://127.0.0.1:18088/ >/dev/null 2>&1 && exit 0; sleep 2; done
docker ps --format "table {{.Names}}\t{{.Ports}}" | grep agentteams-controller || true
exit 2'
  if ! lsof -nP -iTCP:18080 -sTCP:LISTEN >/dev/null 2>&1; then
    echo "Forwarding AgentTeams Matrix and Element ports..."
    gh codespace ports forward 18088:18088 18080:18080 -c "${CODESPACE_NAME}" \
      >"${LOG_DIR}/agentteams-port-forward.log" 2>&1 &
    echo $! >"${LOG_DIR}/agentteams-port-forward.pid"
    sleep 4
  fi
fi

for _ in $(seq 1 30); do
  if curl -fsS "${AGENTTEAMS_MATRIX_BASE_URL}/_matrix/client/versions" >/dev/null 2>&1; then
    break
  fi
  sleep 2
done
if ! curl -fsS "${AGENTTEAMS_MATRIX_BASE_URL}/_matrix/client/versions" >/dev/null 2>&1; then
  cat <<MSG
FAIL: AgentTeams Matrix is still unreachable:
  ${AGENTTEAMS_MATRIX_BASE_URL}/_matrix/client/versions

Keep the Codespace running and make sure port forwarding is active.
Codespace 18088 maps Element to local 18088; Codespace 18080 maps Matrix to local 18080.
MSG
  exit 2
fi

echo "EnergyMesh runtime bridge check:"
export PYTHONPATH="${ROOT}/src:${PYTHONPATH:-}"
"${PYTHON_BIN}" - <<'PY'
from energymesh.agentteams_runtime import probe_agentteams_runtime

status = probe_agentteams_runtime().model_dump()
print(status)
if not status["ready"]:
    raise SystemExit(2)
PY

echo
echo "Starting EnergyMesh white UI on http://127.0.0.1:${ENERGYMESH_PORT}"
echo "AgentTeams Element proof UI: http://127.0.0.1:18088/#/login"
echo "Homeserver: http://127.0.0.1:18080"
echo

exec .venv/bin/uvicorn energymesh.api:app \
  --app-dir src \
  --host "${ENERGYMESH_HOST}" \
  --port "${ENERGYMESH_PORT}"
