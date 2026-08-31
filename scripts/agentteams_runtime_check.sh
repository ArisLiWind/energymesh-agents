#!/usr/bin/env bash
set -euo pipefail

TEAM_NAME="${AGENTTEAMS_TEAM_NAME:-energymesh-park-control}"
RESOURCE_FILE="${1:-agentteams/agentteams-resources.yaml}"

echo "EnergyMesh AgentTeams runtime check"
echo "Team: ${TEAM_NAME}"
echo "Resources: ${RESOURCE_FILE}"
echo

missing=0
if ! command -v docker >/dev/null 2>&1; then
  echo "FAIL docker: not found"
  missing=1
else
  echo "OK docker: $(command -v docker)"
fi

if ! command -v agt >/dev/null 2>&1; then
  echo "FAIL agt: AgentTeams CLI not found"
  missing=1
else
  echo "OK agt: $(command -v agt)"
fi

if [ "${missing}" -ne 0 ]; then
  cat <<'EOF'

AgentTeams is not installed on this machine yet.

Install path:
  1. Install Docker Desktop and verify `docker ps`.
  2. Clone the official runtime:
       git clone https://github.com/agentscope-ai/AgentTeams.git
       cd AgentTeams
       AGENTTEAMS_LLM_API_KEY=<your_key> make install
  3. Apply EnergyMesh resources from this repo:
       agt apply -f agentteams/agentteams-resources.yaml
  4. Verify:
       docker ps | grep agentteams
       agt get workers
       agt get teams

Do not claim live AgentTeams before controller, manager, workers and team are visible.
EOF
  exit 2
fi

echo
echo "Running AgentTeams containers:"
docker ps --format '  {{.Names}}' | grep agentteams || true

echo
echo "Applying resources..."
agt apply -f "${RESOURCE_FILE}"

echo
echo "Workers:"
agt get workers

echo
echo "Teams:"
agt get teams

echo
echo "Runtime check complete. Team must be Active and all EnergyMesh workers must be Running."
