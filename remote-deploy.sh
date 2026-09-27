#!/usr/bin/env bash
set -euo pipefail

# Deploy this checkout to an existing LedgerVault server from your own machine.
#
#   ./remote-deploy.sh user@host /path/to/ledgervault/on/server [ssh-key]
#
# Copies the code with rsync (never .env, keys, node_modules or local data), then
# runs ./deploy.sh on the server. The remote folder must already contain the
# .env created by setup.sh, so this can never start a second, empty stack.
# For a brand-new server, copy the repo there and run ./setup.sh instead.
if [[ $# -lt 2 ]]; then
  sed -n '4,11p' "$0" | sed 's/^# \{0,1\}//'
  exit 1
fi
target="$1"; remote_dir="$2"; key="${3:-}"
ssh_cmd=(ssh -o StrictHostKeyChecking=accept-new)
[[ -n "$key" ]] && ssh_cmd+=(-i "$key")
cd "$(dirname "${BASH_SOURCE[0]}")"

if ! "${ssh_cmd[@]}" "$target" "test -f '$remote_dir/.env'"; then
  echo "No .env in $target:$remote_dir — is that the folder the app runs from?" >&2
  echo "Find it on the server with: docker inspect \$(docker ps -qf name=caddy) --format '{{ index .Config.Labels \"com.docker.compose.project.working_dir\" }}'" >&2
  exit 1
fi
if ! "${ssh_cmd[@]}" "$target" "grep -qE '^SITE_ADDRESS=.+' '$remote_dir/.env'"; then
  echo "SITE_ADDRESS is not set in $remote_dir/.env on the server; without it HTTPS for your domain is turned off." >&2
  echo "Add it first, e.g.:  ssh $target \"echo SITE_ADDRESS=your.domain >> $remote_dir/.env\"" >&2
  exit 1
fi

rsync -az --delete -e "${ssh_cmd[*]}" \
  --exclude '.git/' --exclude '.env' --exclude '.env.*' --exclude '*.pem' --exclude '*.key' \
  --exclude 'node_modules/' --exclude '.next/' --exclude '__pycache__/' --exclude '*.db' \
  --exclude 'private/' --exclude 'statements/' \
  ./ "$target:$remote_dir/"
"${ssh_cmd[@]}" "$target" "cd '$remote_dir' && ./deploy.sh"
