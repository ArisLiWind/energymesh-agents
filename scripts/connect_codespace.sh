#!/bin/bash
# Connect codespace and forward ports for AgentTeams debugging.
# Run this on your LOCAL machine (Mac/Windows/Linux).
#
# Usage:
#   scripts/connect_codespace.sh [CODESPACE_NAME]
#
# If CODESPACE_NAME is not provided, it auto-detects the one for this repo.

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

CODESPACE="${1:-}"

if ! command -v gh >/dev/null 2>&1; then
  echo "ERROR: GitHub CLI (gh) is not installed."
  echo "Install from: https://cli.github.com/"
  exit 2
fi

# Auto-detect codespace for this repo
if [[ -z "$CODESPACE" ]]; then
  REPO="$(git remote get-url origin 2>/dev/null | sed 's/.*github\.com[:/]//' | sed 's/\.git$//' || echo '')"
  if [[ -z "$REPO" ]]; then
    echo "ERROR: Cannot detect repo from git remote. Pass codespace name as argument."
    echo "Example: scripts/connect_codespace.sh energymesh-agentteams-min-q7746qqwx77qcv45"
    exit 2
  fi
  echo "Auto-detecting Codespace for repo: $REPO"
  CODESPACE=$(gh codespace list --repo "$REPO" --json name,state --jq '.[] | select(.state == "Available" or .state == "Shutdown") | .name' 2>/dev/null | head -1 || true)
  if [[ -z "$CODESPACE" ]]; then
    echo "ERROR: No Codespace found for $REPO. Create one on GitHub first."
    exit 2
  fi
  echo "Found codespace: $CODESPACE"
fi

echo ""
echo "=== Connecting to Codespace: $CODESPACE ==="
echo ""

# Check if codespace is running
STATE=$(gh codespace list --json name,state --jq ".[] | select(.name == \"$CODESPACE\") | .state" 2>/dev/null || echo "unknown")
if [[ "$STATE" == "Shutdown" ]]; then
  echo "Codespace is sleeping. Waking up... (this may take 30-60s)"
  # Codespace doesn't have a start command, but ssh will auto-start it
fi

# Test SSH connectivity
echo "Testing SSH connectivity..."
git config --global --replace-all codespaces.require-license-acceptance false 2>/dev/null || true
if ! gh codespace ssh -c "$CODESPACE" -- "echo 'Codespace ready'" >/dev/null 2>&1; then
  echo "ERROR: Cannot SSH into codespace. Make sure the codespace is available."
  exit 2
fi

echo "✓ Codespace SSH OK"
echo ""

# Start Docker containers if any are stopped
echo "Checking Docker containers..."
gh codespace ssh -c "$CODESPACE" -- "docker ps -a --format '{{.Names}} {{.Status}}' | grep -E 'agentteams|Exit' || true" 2>/dev/null || true

# Auto-start stopped containers
echo "Ensuring containers are running..."
gh codespace ssh -c "$CODESPACE" -- "docker ps -q -f 'status=exited' | xargs -r docker start 2>/dev/null || true" 2>/dev/null || true

echo "Starting port forwarding..."
echo "  remote 18080 (Matrix)  <=> local 18080"
echo "  remote 18088 (Element) <=> local 18088"
echo ""

# Kill existing port forwards for these ports (if any)
pkill -f "gh codespace ports forward.*18080.*18088" 2>/dev/null || true
sleep 1

# Start port forwarding in background
LOG_FILE="${ROOT}/runs/codespace-port-forward.log"
mkdir -p "$(dirname "$LOG_FILE")"

gh codespace ports forward 18080:18080 18088:18088 -c "$CODESPACE" >"$LOG_FILE" 2>&1 &
FORWARD_PID=$!
echo $FORWARD_PID > /tmp/energymesh-port-forward.pid
sleep 3

# Test local connectivity
echo "Testing local ports..."
MATRIX_OK=false
ELEMENT_OK=false

if curl -fsS http://127.0.0.1:18080/_matrix/client/versions >/dev/null 2>&1; then
  echo "✓ Matrix homeserver: http://127.0.0.1:18080"
  MATRIX_OK=true
else
  echo "✗ Matrix homeserver not reachable on 18080"
fi

if curl -fsS -o /dev/null -w '%{http_code}' http://127.0.0.1:18088 >/dev/null 2>&1; then
  echo "✓ Element web:       http://127.0.0.1:18088"
  ELEMENT_OK=true
else
  echo "✗ Element web not reachable on 18088"
fi

echo ""

if [[ "$MATRIX_OK" == true && "$ELEMENT_OK" == true ]]; then
  echo "============================================"
  echo "🎉 All systems connected!"
  echo ""
  echo "Matrix API:  http://127.0.0.1:18080"
  echo "Element UI:  http://127.0.0.1:18088"
  echo ""
  echo "Port forward PID: $FORWARD_PID"
  echo "Log file: $LOG_FILE"
  echo "============================================"
  echo ""
  echo "To start keepalive on the codespace (prevents idle timeout):"
  echo "  gh codespace ssh -c $CODESPACE -- \"bash scripts/start_codespace_keepalive.sh\""
  echo ""
  echo "To stop port forwarding:"
  echo "  kill $FORWARD_PID"
  echo ""
  echo "Press Ctrl+C to stop this script (port forward will continue in background)."
  echo ""
else
  echo "WARNING: Some services are not reachable. Check the codespace state."
  echo "Log file: $LOG_FILE"
  exit 1
fi

# Keep script running so user can see the status
trap 'echo ""; echo "Stopping port forward..."; kill "$FORWARD_PID" 2>/dev/null || true; exit 0' INT
wait "$FORWARD_PID" 2>/dev/null || true
