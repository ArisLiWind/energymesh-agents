#!/bin/bash
# EnergyMesh Local Multi-Worker Keep-Alive Script
# 用途: 本地调试期间防止 Docker 容器休眠 / FastAPI 进程退出
# 运行: nohup bash scripts/local_keepalive.sh > runs/keepalive.log 2>&1 &
#
# 与 codespace_keepalive.sh 的关系:
#   - codespace_keepalive.sh: 在 GitHub Codespaces 内部运行，防止 Codespace 空闲超时
#   - local_keepalive.sh:    在本地开发机上运行，监控本地服务健康状态

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LOG_FILE="${ROOT}/runs/keepalive.log"
HEARTBEAT_FILE="/tmp/energymesh_keepalive"
INTERVAL="${KEEPALIVE_INTERVAL:-180}"  # 默认 3 分钟

# ---- 可配置的服务端口 ----
ENERGYMESH_PORT="${ENERGYMESH_PORT:-8000}"
MATRIX_PORT="${AGENTTEAMS_MATRIX_PORT:-18080}"
ELEMENT_PORT="${AGENTTEAMS_ELEMENT_PORT:-18088}"
MANAGER_PORT="${AGENTTEAMS_MANAGER_PORT:-18888}"

# ---- Docker 容器名称 ----
CONTAINERS=(
    "agentteams-controller"
    "agentteams-manager"
    "agentteams-worker-energy-dispatcher"
)

mkdir -p "$(dirname "$LOG_FILE")"

log() {
    echo "$(date '+%Y-%m-%d %H:%M:%S')  $1" | tee -a "$LOG_FILE"
}

# ---- 端口检测 ----
check_port() {
    local host="$1"
    local port="$2"
    local label="$3"
    if curl -fsS --max-time 5 "http://${host}:${port}" >/dev/null 2>&1; then
        return 0
    else
        log "WARN  ${label} (${host}:${port}) 不可达"
        return 1
    fi
}

# ---- 容器保活 ----
ensure_container_running() {
    local name="$1"
    if ! docker inspect "$name" >/dev/null 2>&1; then
        return 0
    fi
    local state
    state="$(docker inspect -f '{{.State.Status}}' "$name" 2>/dev/null || echo "unknown")"
    if [[ "$state" != "running" ]]; then
        log "WARN  容器 ${name} 状态=${state}，尝试启动..."
        docker start "$name" 2>&1 | tee -a "$LOG_FILE" || log "ERROR 无法启动容器 ${name}"
    fi
    # 确保 restart policy 为 unless-stopped
    local policy
    policy="$(docker inspect -f '{{.HostConfig.RestartPolicy.Name}}' "$name" 2>/dev/null || echo "none")"
    if [[ "$policy" == "no" || "$policy" == "" ]]; then
        docker update --restart unless-stopped "$name" 2>/dev/null || true
        log "INFO  ${name} restart policy → unless-stopped"
    fi
}

# ---- 综合健康检查 ----
health_report() {
    local ok=0
    local fail=0
    local details=()

    # 1. EnergyMesh FastAPI
    if check_port "127.0.0.1" "$ENERGYMESH_PORT" "EnergyMesh"; then
        ((ok++))
        details+=("EnergyMesh:OK")
    else
        ((fail++))
        details+=("EnergyMesh:DOWN")
    fi

    # 2. Matrix Homeserver
    if check_port "127.0.0.1" "$MATRIX_PORT" "Matrix"; then
        ((ok++))
        details+=("Matrix:OK")
    else
        details+=("Matrix:OFFLINE")
    fi

    # 3. AgentTeams Manager
    if check_port "127.0.0.1" "$MANAGER_PORT" "Manager"; then
        ((ok++))
        details+=("Manager:OK")
    else
        details+=("Manager:OFFLINE")
    fi

    # 4. Element Web UI
    if check_port "127.0.0.1" "$ELEMENT_PORT" "Element"; then
        ((ok++))
        details+=("Element:OK")
    else
        details+=("Element:OFFLINE")
    fi

    # 5. Docker 容器状态
    for c in "${CONTAINERS[@]}"; do
        if docker inspect "$c" >/dev/null 2>&1; then
            local st
            st="$(docker inspect -f '{{.State.Status}}' "$c" 2>/dev/null || echo "?")"
            if [[ "$st" == "running" ]]; then
                ((ok++))
                details+=("${c}:running")
            else
                ((fail++))
                details+=("${c}:${st}")
                ensure_container_running "$c"
            fi
        fi
    done

    log "HEALTH ${ok}/$((ok+fail)) 通过 | ${details[*]}"
}

# ---- 信号处理 ----
cleanup() {
    log "=== Keep-Alive 收到停止信号 ==="
    rm -f "$HEARTBEAT_FILE"
    exit 0
}

trap cleanup INT TERM

# ---- 主入口 ----
log "=== EnergyMesh Local Keep-Alive Started ==="
log "PID: $$  INTERVAL: ${INTERVAL}s"
log "EnergyMesh :${ENERGYMESH_PORT}  Matrix :${MATRIX_PORT}  Manager :${MANAGER_PORT}  Element :${ELEMENT_PORT}"
log ""

# 首次初始化：确保所有已知容器运行且配置 restart policy
for c in "${CONTAINERS[@]}"; do
    ensure_container_running "$c"
done

while true; do
    touch "$HEARTBEAT_FILE"
    touch "${ROOT}/.keepalive" 2>/dev/null || true

    health_report

    sleep "$INTERVAL"
done