#!/usr/bin/env bash
set -euo pipefail

RESOURCE_FILE="${1:-agentteams/agentteams-resources.yaml}"

echo "EnergyMesh live AgentTeams setup"
echo "Resource file: ${RESOURCE_FILE}"
echo

if ! command -v docker >/dev/null 2>&1; then
  cat <<'MSG'
FAIL docker: Docker is not installed or not available in PATH.

Install Docker Desktop first, start it, then verify:
  docker ps

EnergyMesh will not run the local fallback when AGENTTEAMS_LIVE_REQUIRED=true.
MSG
  exit 2
fi

if ! docker ps >/dev/null 2>&1; then
  cat <<'MSG'
FAIL docker: Docker exists, but the daemon is not reachable.

Start Docker Desktop, then verify:
  docker ps
MSG
  exit 2
fi

if ! command -v agt >/dev/null 2>&1; then
  cat <<'MSG'
FAIL agt: official AgentTeams CLI is not installed.

Install the upstream runtime:
  git clone https://github.com/agentscope-ai/AgentTeams.git
  cd AgentTeams
  AGENTTEAMS_LLM_API_KEY=<your-model-key> make install

Then return to this repository and rerun:
  scripts/setup_live_agentteams.sh
MSG
  exit 2
fi

if [[ ! -f "${RESOURCE_FILE}" ]]; then
  echo "FAIL resources: ${RESOURCE_FILE} does not exist."
  exit 2
fi

echo "Applying EnergyMesh Worker, Human and Team resources..."
agt apply -f "${RESOURCE_FILE}"

echo
echo "AgentTeams workers:"
agt get workers

echo
echo "AgentTeams teams:"
agt get teams

echo
echo "Docker AgentTeams containers:"
docker ps --format '  {{.Names}}' | grep agentteams || true

cat <<'MSG'

Next required bridge variables for the FastAPI/UI live chat path:
  export AGENTTEAMS_LIVE_REQUIRED=true
  export AGENTTEAMS_TEAM_ROOM_ID=<matrix-room-id-created-by-agentteams>
  export AGENTTEAMS_MATRIX_BASE_URL=<matrix-client-base-url>
  export AGENTTEAMS_MATRIX_ACCESS_TOKEN=<matrix-access-token-for-fastapi-bridge>
  export AGENTTEAMS_EVENT_STREAM_URL=<agentteams-manager-or-bridge-sse-url>

Verify from EnergyMesh:
  scripts/agentteams_runtime_check.sh
  curl http://127.0.0.1:8000/api/agentteams/runtime

Only when that endpoint returns ready=true should the UI show live Worker handoff.
MSG
