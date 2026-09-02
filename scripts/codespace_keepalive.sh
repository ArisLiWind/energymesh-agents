#!/bin/bash
# Codespace Keep-Alive Script
# Prevents GitHub Codespace idle timeout by keeping services warm.
# Run this inside the Codespace (not on your local machine).

LOG_FILE="${HOME}/.codespace_keepalive.log"
INTERVAL=300  # 5 minutes

log() {
    echo "$(date '+%Y-%m-%d %H:%M:%S') $1" | tee -a "$LOG_FILE"
}

log "=== Codespace keep-alive started ==="
log "PID: $$"

while true; do
    # Touch heartbeat file to signal activity
    touch /tmp/codespace_keepalive

    # Ping local Matrix to keep services warm
    curl -fsS http://127.0.0.1:18080/_matrix/client/versions >/dev/null 2>&1 || true
    curl -fsS http://127.0.0.1:18088 >/dev/null 2>&1 || true

    # Ping manager
    curl -fsS http://127.0.0.1:18888 >/dev/null 2>&1 || true

    # Ping worker
    curl -fsS http://127.0.0.1:12925 >/dev/null 2>&1 || true

    # Touch workspace file so GitHub sees filesystem activity
    touch /workspaces/energymesh-agents/.codespace_alive 2>/dev/null || true

    log "Heartbeat OK"
    sleep "$INTERVAL"
done
