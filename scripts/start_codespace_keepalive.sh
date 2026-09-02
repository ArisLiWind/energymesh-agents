#!/bin/bash
# Start the codespace keepalive service INSIDE the Codespace VM.
# This prevents GitHub Codespace from shutting down due to inactivity.
# Run this AFTER you SSH into the codespace, or run remotely:
#   gh codespace ssh -c <name> -- "bash scripts/start_codespace_keepalive.sh"

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

KEEPALIVE_SCRIPT="$ROOT/scripts/codespace_keepalive.sh"
LOG_DIR="$ROOT/runs"
mkdir -p "$LOG_DIR"

echo "=== AgentTeams Codespace Keepalive ==="
echo ""

# Check if keepalive is already running
if pgrep -f "codespace_keepalive.sh" >/dev/null 2>&1; then
  PID=$(pgrep -f "codespace_keepalive.sh" | head -1)
  echo "✓ Keepalive is already running (PID: $PID)"
  echo "  Log: $HOME/.codespace_keepalive.log"
  echo ""
else
  if [[ ! -f "$KEEPALIVE_SCRIPT" ]]; then
    echo "ERROR: $KEEPALIVE_SCRIPT not found."
    exit 2
  fi

  chmod +x "$KEEPALIVE_SCRIPT"
  nohup bash "$KEEPALIVE_SCRIPT" >/dev/null 2>&1 &
  sleep 2
  PID=$(pgrep -f "codespace_keepalive.sh" | head -1 || echo "unknown")
  echo "✓ Keepalive started (PID: $PID)"
  echo "  Log: $HOME/.codespace_keepalive.log"
  echo "  Heartbeat interval: 5 minutes"
  echo ""
fi

# Ensure Docker containers have restart policies
echo "Setting container auto-restart policies..."
for container in agentteams-controller agentteams-manager agentteams-worker-energy-dispatcher; do
  if docker inspect "$container" >/dev/null 2>&1; then
    CURRENT_POLICY=$(docker inspect -f '{{.HostConfig.RestartPolicy.Name}}' "$container" 2>/dev/null || echo "none")
    if [[ "$CURRENT_POLICY" == "no" ]]; then
      docker update --restart unless-stopped "$container" 2>/dev/null || true
      echo "  ✓ $container → unless-stopped"
    else
      echo "  ✓ $container → $CURRENT_POLICY (OK)"
    fi
  else
    echo "  ⚠ $container not found"
  fi
done

# Show container status
echo ""
echo "Container status:"
docker ps -a --format '  {{.Names}} {{.Status}}' 2>/dev/null | grep agentteams || echo "  (no agentteams containers found)"

echo ""
echo "============================================"
echo "Keepalive is running!"
echo ""
echo "This scripts pings local services every 5 min"
echo "and touches workspace files to keep the"
echo "Codespace alive and warm."
echo ""
echo "Note: GitHub Codespaces have a max idle timeout"
echo "of 4 hours (240 min). If you need longer uptime,"
echo "consider running on a dedicated server or VM."
echo "============================================"
