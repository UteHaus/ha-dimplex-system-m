#!/usr/bin/env bash
#
# dimplex_uhi_tunnel.sh
#
# Option 1: reach the UHI REST/Socket.IO API through an SSH tunnel WITHOUT
# changing anything on the UHI device and WITHOUT opening the firewall.
#
# How it works:
#   The UHI firewall allows SSH (tcp/22) and the loopback interface (lo).
#   We open an SSH local port-forward so a port on THIS machine is forwarded
#   over SSH to 127.0.0.1:<API_PORT> on the device — where the API is reachable
#   locally. REST and the Socket.IO WebSocket both travel through the one tunnel.
#
# After it runs, point Home Assistant / the bridge at:
#   UHI_BASE_URL=http://localhost:<LOCAL_PORT>
#   UHI_SOCKET_URL=http://localhost:<LOCAL_PORT>
#
# The tunnel stays in the foreground (Ctrl+C to stop). If `autossh` is
# installed it is used to auto-reconnect on drops.

set -euo pipefail

# ---------------------------------------------------------------------------
# Defaults (can be overridden interactively)
# ---------------------------------------------------------------------------
SSH_USER="pi"
SSH_HOST=""
SSH_PORT=22
SSH_KEY=""
LOCAL_PORT="8080"
API_PORT=80
BIND_ADDR="127.0.0.1"

ask() {
  # ask "Prompt" "default" -> echoes the answer (default if empty input)
  local prompt="$1" default="${2:-}" answer
  if [[ -n "$default" ]]; then
    read -rp "$prompt [$default]: " answer
    printf '%s' "${answer:-$default}"
  else
    read -rp "$prompt: " answer
    printf '%s' "$answer"
  fi
}

echo "=== UHI API via SSH tunnel (firewall stays enabled) ==="

SSH_USER="$(ask 'SSH user' "$SSH_USER")"
SSH_HOST="$(ask 'SSH host (UHI IP/hostname)' "$SSH_HOST")"
while [[ -z "$SSH_HOST" ]]; do
  SSH_HOST="$(ask 'SSH host is required' '')"
done
SSH_PORT="$(ask 'SSH port' "$SSH_PORT")"
SSH_KEY="$(ask 'SSH key file (empty = password/agent)' "$SSH_KEY")"

# The local port to use for the tunnel must be specified.
LOCAL_PORT="$(ask 'Local port to use on THIS machine' "$LOCAL_PORT")"
while ! [[ "$LOCAL_PORT" =~ ^[0-9]+$ ]] || (( LOCAL_PORT < 1 || LOCAL_PORT > 65535 )); do
  LOCAL_PORT="$(ask 'Local port must be a number 1-65535' '')"
done

API_PORT="$(ask 'UHI API port on the device' "$API_PORT")"
BIND_ADDR="$(ask 'Local bind address (127.0.0.1 = only this host, 0.0.0.0 = LAN)' "$BIND_ADDR")"

# ---------------------------------------------------------------------------
# Build SSH options
# ---------------------------------------------------------------------------
SSH_OPTS=(
  -p "$SSH_PORT"
  -o ConnectTimeout=10
  -o StrictHostKeyChecking=accept-new
  -o ServerAliveInterval=15
  -o ServerAliveCountMax=3
  -o ExitOnForwardFailure=yes
)
if [[ -n "$SSH_KEY" ]]; then
  [[ -f "$SSH_KEY" ]] || { echo "SSH key not found: $SSH_KEY" >&2; exit 1; }
  SSH_OPTS+=(-i "$SSH_KEY" -o IdentitiesOnly=yes)
fi

FORWARD="${BIND_ADDR}:${LOCAL_PORT}:127.0.0.1:${API_PORT}"

echo
echo "Tunnel: http://${BIND_ADDR}:${LOCAL_PORT}  ->  ${SSH_USER}@${SSH_HOST}:${SSH_PORT}  ->  127.0.0.1:${API_PORT}"
echo "Use in Home Assistant / bridge .env:"
echo "  UHI_BASE_URL=http://localhost:${LOCAL_PORT}"
echo "  UHI_SOCKET_URL=http://localhost:${LOCAL_PORT}"
echo
echo "Starting tunnel (Ctrl+C to stop)..."
echo

# -N = no remote command, just forward. -L = local forward.
if command -v autossh >/dev/null 2>&1; then
  exec autossh -M 0 -N -L "$FORWARD" "${SSH_OPTS[@]}" "${SSH_USER}@${SSH_HOST}"
else
  echo "(tip: install 'autossh' for automatic reconnect)"
  exec ssh -N -L "$FORWARD" "${SSH_OPTS[@]}" "${SSH_USER}@${SSH_HOST}"
fi
