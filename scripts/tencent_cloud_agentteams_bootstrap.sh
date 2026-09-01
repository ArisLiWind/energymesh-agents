#!/usr/bin/env bash
set -euo pipefail

AGENTTEAMS_REPO="${AGENTTEAMS_REPO:-https://github.com/agentscope-ai/AgentTeams.git}"
AGENTTEAMS_DIR="${AGENTTEAMS_DIR:-$HOME/AgentTeams}"
RESOURCE_FILE="${RESOURCE_FILE:-agentteams/agentteams-resources.yaml}"

if [[ -z "${AGENTTEAMS_LLM_API_KEY:-}" ]]; then
  echo "FAIL: AGENTTEAMS_LLM_API_KEY is required for official AgentTeams installation." >&2
  exit 2
fi

if ! command -v apt-get >/dev/null 2>&1; then
  echo "FAIL: this bootstrap targets Ubuntu/Debian Tencent Cloud CVMs." >&2
  exit 2
fi

if ! command -v docker >/dev/null 2>&1; then
  echo "Installing Docker Engine..."
  sudo apt-get update
  sudo apt-get install -y ca-certificates curl gnupg git make
  sudo install -m 0755 -d /etc/apt/keyrings
  curl -fsSL https://download.docker.com/linux/ubuntu/gpg | sudo gpg --dearmor -o /etc/apt/keyrings/docker.gpg
  sudo chmod a+r /etc/apt/keyrings/docker.gpg
  . /etc/os-release
  echo \
    "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/ubuntu \
    ${VERSION_CODENAME} stable" | sudo tee /etc/apt/sources.list.d/docker.list >/dev/null
  sudo apt-get update
  sudo apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
fi

sudo systemctl enable --now docker
docker ps >/dev/null || sudo usermod -aG docker "$USER"

if [[ ! -d "${AGENTTEAMS_DIR}/.git" ]]; then
  git clone "${AGENTTEAMS_REPO}" "${AGENTTEAMS_DIR}"
fi

echo "Installing official AgentTeams runtime..."
(
  cd "${AGENTTEAMS_DIR}"
  AGENTTEAMS_LLM_API_KEY="${AGENTTEAMS_LLM_API_KEY}" make install
)

if ! command -v agt >/dev/null 2>&1; then
  echo "FAIL: agt CLI is still unavailable after AgentTeams install." >&2
  exit 2
fi

echo "Applying EnergyMesh AgentTeams resources..."
agt apply -f "${RESOURCE_FILE}"

echo
echo "Workers:"
agt get workers

echo
echo "Teams:"
agt get teams

echo
echo "Containers:"
docker ps --format '  {{.Names}}' | grep agentteams || true

cat <<'MSG'

Cloud runtime bootstrap finished.

Now expose only the Team Room bridge and event stream endpoint needed by EnergyMesh FastAPI:
  AGENTTEAMS_TEAM_ROOM_ID
  AGENTTEAMS_MATRIX_BASE_URL
  AGENTTEAMS_MATRIX_ACCESS_TOKEN
  AGENTTEAMS_EVENT_STREAM_URL

Do not expose Docker or AgentTeams internal control ports publicly.
MSG
