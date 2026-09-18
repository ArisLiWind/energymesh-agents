#!/usr/bin/env bash
set -euo pipefail

ROOT="${ENERGYMESH_ROOT:-/opt/energymesh}"
AGENTTEAMS_DIR="${AGENTTEAMS_DIR:-/opt/AgentTeams}"
ENV_FILE="${ENV_FILE:-${ROOT}/.env.agentteams.local}"
LOG_FILE="${LOG_FILE:-${ROOT}/runs/ecs-agentteams-keepalive.log}"
INTERVAL="${KEEPALIVE_INTERVAL:-120}"
TEAM_NAME="${AGENTTEAMS_TEAM_NAME:-energymesh-park-control}"
RESOURCE_FILE="${RESOURCE_FILE:-${ROOT}/agentteams/agentteams-resources.yaml}"

mkdir -p "$(dirname "${LOG_FILE}")"

log() {
  printf '%s %s\n' "$(date '+%Y-%m-%d %H:%M:%S')" "$*" | tee -a "${LOG_FILE}"
}

load_env() {
  if [[ -f "${ENV_FILE}" ]]; then
    set -a
    # shellcheck disable=SC1090
    source "${ENV_FILE}"
    set +a
  fi
}

require_secret() {
  if [[ -z "${AGENTTEAMS_LLM_API_KEY:-}" ]]; then
    log "WAIT AGENTTEAMS_LLM_API_KEY is not configured in ${ENV_FILE}"
    return 1
  fi
  return 0
}

ensure_repo() {
  if [[ -d "${AGENTTEAMS_DIR}/.git" ]]; then
    git -C "${AGENTTEAMS_DIR}" fetch --depth 1 origin main >/dev/null 2>&1 || true
    git -C "${AGENTTEAMS_DIR}" checkout -q main >/dev/null 2>&1 || true
    git -C "${AGENTTEAMS_DIR}" pull --ff-only >/dev/null 2>&1 || true
    return
  fi
  mkdir -p "$(dirname "${AGENTTEAMS_DIR}")"
  git clone --depth 1 https://github.com/agentscope-ai/AgentTeams.git "${AGENTTEAMS_DIR}"
}

install_or_repair_runtime() {
  require_secret || return 0
  ensure_repo
  cd "${AGENTTEAMS_DIR}"
  AGENTTEAMS_NON_INTERACTIVE=1 \
  AGENTTEAMS_UPGRADE_KEEP_ALL=1 \
  AGENTTEAMS_MATRIX_E2EE=0 \
  AGENTTEAMS_MOUNT_SOCKET=1 \
  bash ./install/agentteams-install.sh >>"${LOG_FILE}" 2>&1
}

ensure_restart_policy() {
  local names
  names="$(docker ps -a --format '{{.Names}}' | grep '^agentteams-' || true)"
  while read -r name; do
    [[ -n "${name}" ]] || continue
    docker update --restart unless-stopped "${name}" >/dev/null 2>&1 || true
    state="$(docker inspect -f '{{.State.Status}}' "${name}" 2>/dev/null || true)"
    if [[ "${state}" != "running" ]]; then
      log "START ${name} state=${state:-unknown}"
      docker start "${name}" >>"${LOG_FILE}" 2>&1 || true
    fi
  done <<<"${names}"
}

apply_resources() {
  if [[ -f "${RESOURCE_FILE}" ]] && docker ps --format '{{.Names}}' | grep -q '^agentteams-controller$'; then
    docker exec agentteams-controller agt apply -f "${RESOURCE_FILE}" >>"${LOG_FILE}" 2>&1 || true
  fi
}

runtime_ready() {
  docker ps --format '{{.Names}}' | grep -q '^agentteams-controller$' || return 1
  docker ps --format '{{.Names}}' | grep -q '^agentteams-manager' || return 1
  docker exec agentteams-controller agt get teams 2>/dev/null | grep -q "${TEAM_NAME}" || return 1
}

main_loop() {
  log "START EnergyMesh ECS AgentTeams keepalive root=${ROOT} agentteams=${AGENTTEAMS_DIR}"
  while true; do
    load_env
    if ! command -v docker >/dev/null 2>&1; then
      log "WAIT docker is not installed"
      sleep "${INTERVAL}"
      continue
    fi
    if ! docker ps >/dev/null 2>&1; then
      log "WAIT docker daemon is not reachable"
      sleep "${INTERVAL}"
      continue
    fi
    if runtime_ready; then
      ensure_restart_policy
      log "OK AgentTeams runtime ready"
    else
      log "REPAIR AgentTeams runtime not ready"
      install_or_repair_runtime
      ensure_restart_policy
      apply_resources
    fi
    sleep "${INTERVAL}"
  done
}

main_loop
