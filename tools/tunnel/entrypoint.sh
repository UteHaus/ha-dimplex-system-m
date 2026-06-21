#!/bin/sh
# Opens an SSH local port-forward to the UHI API and keeps it alive.
#
#   container:${LOCAL_PORT}  ->  ssh ${SSH_USER}@${SSH_HOST}:${SSH_PORT}
#                            ->  127.0.0.1:${API_PORT} on the UHI device
#
# UHI's firewall allows SSH (tcp/22) and loopback (lo), so the forwarded
# traffic reaches the API locally on the device. No UHI change required.
#
# Requires SSH KEY auth (a container cannot type a password): mount the
# private key and point SSH_KEY at it.
set -eu

: "${SSH_HOST:?SSH_HOST is required}"
SSH_USER="${SSH_USER:-pi}"
SSH_PORT="${SSH_PORT:-22}"
LOCAL_PORT="${LOCAL_PORT:-8080}"
API_PORT="${API_PORT:-80}"
SSH_KEY="${SSH_KEY:-/keys/id_uhi}"

if [ ! -f "$SSH_KEY" ]; then
  echo "ERROR: SSH key not found at $SSH_KEY (mount it read-only)." >&2
  exit 1
fi

echo "Tunnel: 0.0.0.0:${LOCAL_PORT} -> ${SSH_USER}@${SSH_HOST}:${SSH_PORT} -> 127.0.0.1:${API_PORT}"

# -M 0 disables autossh's own monitoring port; ServerAlive does the liveness.
# Bind 0.0.0.0 so other compose services can reach the forwarded port.
exec autossh -M 0 -N \
  -i "$SSH_KEY" \
  -p "$SSH_PORT" \
  -L "0.0.0.0:${LOCAL_PORT}:127.0.0.1:${API_PORT}" \
  -o IdentitiesOnly=yes \
  -o StrictHostKeyChecking=accept-new \
  -o UserKnownHostsFile=/tmp/known_hosts \
  -o ServerAliveInterval=15 \
  -o ServerAliveCountMax=3 \
  -o ExitOnForwardFailure=yes \
  "${SSH_USER}@${SSH_HOST}"
