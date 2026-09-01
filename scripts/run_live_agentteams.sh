#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
AGENTTEAMS_DIR="${AGENTTEAMS_DIR:-/Users/zhuanz1mima0000/Documents/New project/AgentTeams}"
ENV_FILE="${ENV_FILE:-${ROOT}/.env.agentteams.local}"
LOG_FILE="${LOG_FILE:-${ROOT}/runs/agentteams-live-install.log}"

mkdir -p "$(dirname "${LOG_FILE}")"

if [[ ! -d "${AGENTTEAMS_DIR}" ]]; then
  echo "FAIL: official AgentTeams repo not found: ${AGENTTEAMS_DIR}" | tee -a "${LOG_FILE}"
  exit 2
fi

if [[ ! -f "${ENV_FILE}" ]]; then
  echo "FAIL: env file not found: ${ENV_FILE}" | tee -a "${LOG_FILE}"
  exit 2
fi

{
  echo
  echo "== EnergyMesh live AgentTeams run =="
  date
  echo "AgentTeams: ${AGENTTEAMS_DIR}"
  echo "Env: ${ENV_FILE}"
  echo "Log: ${LOG_FILE}"
} | tee -a "${LOG_FILE}"

set -a
# shellcheck disable=SC1090
source "${ENV_FILE}"
set +a

cd "${AGENTTEAMS_DIR}"
AGENTTEAMS_INSTALL_EMBEDDED_IMAGE="${AGENTTEAMS_INSTALL_EMBEDDED_IMAGE:-agentteams/agentteams-embedded:latest}" \
AGENTTEAMS_NON_INTERACTIVE=1 \
AGENTTEAMS_UPGRADE_KEEP_ALL=1 \
AGENTTEAMS_MATRIX_E2EE=0 \
AGENTTEAMS_MOUNT_SOCKET=1 \
bash ./install/agentteams-install.sh 2>&1 | tee -a "${LOG_FILE}"

echo "== Docker containers ==" | tee -a "${LOG_FILE}"
docker ps --format '{{.Names}} {{.Status}}' | tee -a "${LOG_FILE}"

echo "== AgentTeams workers ==" | tee -a "${LOG_FILE}"
docker exec agentteams-controller agt get workers | tee -a "${LOG_FILE}"

echo "== AgentTeams teams ==" | tee -a "${LOG_FILE}"
docker exec agentteams-controller agt get teams | tee -a "${LOG_FILE}"
