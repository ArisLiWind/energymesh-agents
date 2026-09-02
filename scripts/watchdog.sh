#!/bin/bash
# EnergyMesh AgentTeams Watchdog
# Run this on your LOCAL machine. It keeps the codespace alive and ports forwarded.
#
# Usage:
#   bash scripts/watchdog.sh [CODESPACE_NAME]
#
# It auto-detects the codespace, wakes it up if sleeping, and rebuilds port forwards.
# Run it in a dedicated terminal/tmux window and leave it running.

set -euo pipefail

CODESPACE="${1:-}"
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LOG_DIR="${ROOT}/runs"
mkdir -p "$LOG_DIR"
LOG_FILE="${LOG_DIR}/watchdog.log"

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

log() {
    local msg="[$(date '+%H:%M:%S')] $1"
    echo -e "$msg" | tee -a "$LOG_FILE"
}

# Auto-detect codespace
if [[ -z "$CODESPACE" ]]; then
    REPO="$(git -C "$ROOT" remote get-url origin 2>/dev/null | sed 's/.*github\.com[:/]//' | sed 's/\.git$//' || echo '')"
    if [[ -z "$REPO" ]]; then
        log "${RED}ERROR: Cannot detect repo. Pass codespace name.${NC}"
        exit 2
    fi
    CODESPACE=$(gh codespace list --repo "$REPO" --json name,state --jq '.[] | select(.state == "Available" or .state == "Shutdown") | .name' 2>/dev/null | head -1 || true)
    if [[ -z "$CODESPACE" ]]; then
        log "${RED}ERROR: No codespace found for $REPO.${NC}"
        exit 2
    fi
    log "${BLUE}Auto-detected codespace: $CODESPACE${NC}"
fi

# Kill old port forward processes for this codespace
kill_old_forward() {
    pgrep -f "gh codespace ports forward.*18080.*18088" 2>/dev/null | while read pid; do
        kill "$pid" 2>/dev/null || true
    done
    sleep 1
}

# Wake up codespace by SSH touch
wake_codespace() {
    log "${YELLOW}Codespace sleeping. Waking up...${NC}"
    gh codespace ssh -c "$CODESPACE" -- "echo 'wake'" >/dev/null 2>&1 || {
        log "${YELLOW}Still waking, retrying...${NC}"
        sleep 15
        gh codespace ssh -c "$CODESPACE" -- "echo 'wake'" >/dev/null 2>&1 || {
            log "${RED}Wake failed. Retrying in 30s.${NC}"
            sleep 30
            return 1
        }
    }
    # Start any exited containers
    gh codespace ssh -c "$CODESPACE" -- "docker ps -q -f 'status=exited' | xargs -r docker start 2>/dev/null || true" >/dev/null 2>&1 || true
    log "${GREEN}Codespace awake and containers started.${NC}"
    return 0
}

# Establish port forward
start_forward() {
    kill_old_forward
    sleep 1
    gh codespace ports forward 18080:18080 18088:18088 -c "$CODESPACE" >>"$LOG_FILE" 2>&1 &
    FORWARD_PID=$!
    echo "$FORWARD_PID" > /tmp/em_watchdog_forward.pid
    log "${GREEN}Port forward started (PID: $FORWARD_PID)${NC}"
    sleep 4
}

# Test connectivity
test_ports() {
    local matrix_ok=false
    local element_ok=false
    if curl -fsS http://127.0.0.1:18080/_matrix/client/versions >/dev/null 2>&1; then
        matrix_ok=true
    fi
    if curl -fsS -o /dev/null -w '%{http_code}' http://127.0.0.1:18088 >/dev/null 2>&1; then
        element_ok=true
    fi
    if [[ "$matrix_ok" == true && "$element_ok" == true ]]; then
        return 0
    fi
    return 1
}

# ===== MAIN LOOP =====
log "${BLUE}========================================${NC}"
log "${BLUE}  EnergyMesh AgentTeams Watchdog${NC}"
log "${BLUE}  Codespace: $CODESPACE${NC}"
log "${BLUE}========================================${NC}"

while true; do
    if test_ports; then
        # All good, just log occasionally
        if [[ $(($(date +%s) % 300)) -lt 15 ]]; then
            log "${GREEN}✓ Matrix + Element online${NC}"
        fi
        sleep 30
    else
        log "${YELLOW}⚠ Connection lost. Reconnecting...${NC}"
        if ! wake_codespace; then
            log "${RED}⚠ Wake failed, will retry in 60s${NC}"
            sleep 60
            continue
        fi
        start_forward
        sleep 5
        if test_ports; then
            log "${GREEN}✅ Reconnected!${NC}"
            log "${GREEN}  Matrix:  http://127.0.0.1:18080${NC}"
            log "${GREEN}  Element: http://127.0.0.1:18088${NC}"
        else
            log "${RED}⚠ Still unreachable after forward. Retrying in 60s.${NC}"
            sleep 60
        fi
    fi
done
