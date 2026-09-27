#!/usr/bin/env bash
set -euo pipefail

# Deploy this checkout to an existing LedgerVault server from your own machine.
#
#   ./remote-deploy.sh user@host /path/to/ledgervault/on/server [ssh-key]
#
# Copies the files tracked by git with rsync (never .env, keys or local data), then
# runs ./deploy.sh on the server. The remote folder must already contain the
# .env created by setup.sh, so this can never start a second, empty stack.
# For a brand-new server, copy the repo there and run ./setup.sh instead.
if [[ $# -lt 2 ]]; then
  sed -n '4,11p' "$0" | sed 's/^# \{0,1\}//'
  exit 1
fi
target="$1"; remote_dir="$2"; key="${3:-}"
ssh_cmd=(ssh -o StrictHostKeyChecking=accept-new -o ConnectTimeout=15 -o ServerAliveInterval=30 -o ServerAliveCountMax=6)
[[ -n "${key}" ]] && ssh_cmd+=(-i "${key}")
cd "$(dirname "${BASH_SOURCE[0]}")"
if [[ -n "$(git status --porcelain --untracked-files=no)" ]]; then
  echo "You have uncommitted changes to tracked files; commit or stash them first so the server gets exactly this branch." >&2
  exit 1
fi

echo "-> Connecting to ${target}..."
if ! "${ssh_cmd[@]}" "${target}" true; then
  echo "Can't reach ${target}. Is the server on and your VPN/Tailscale connected?" >&2
  exit 1
fi
if ! "${ssh_cmd[@]}" "${target}" "test -f '${remote_dir}/.env'"; then
  echo "No .env in ${target}:${remote_dir} - is that the folder the app runs from?" >&2
  echo "Find it on the server with: docker inspect \$(docker ps -qf name=caddy) --format '{{ index .Config.Labels \"com.docker.compose.project.working_dir\" }}'" >&2
  exit 1
fi
if ! "${ssh_cmd[@]}" "${target}" "grep -qE '^SITE_ADDRESS=.+' '${remote_dir}/.env'"; then
  echo "SITE_ADDRESS is not set in ${remote_dir}/.env on the server; without it HTTPS for your domain is turned off." >&2
  echo "Add it first, e.g.:  ssh ${target} \"echo SITE_ADDRESS=your.domain >> ${remote_dir}/.env\"" >&2
  exit 1
fi

# Only files tracked by git are sent, so personal files that happen to sit in this
# folder (statements, tax PDFs, .env, keys) never leave your machine.
echo "-> Copying $(git ls-files | wc -l | tr -d ' ') files (commit $(git rev-parse --short HEAD))..."
git ls-files -z | rsync -az --from0 --files-from=- -e "${ssh_cmd[*]}" ./ "${target}:${remote_dir}/"
echo "-> Building and restarting on the server (the first build after an update can take 5-10 minutes)..."
"${ssh_cmd[@]}" "${target}" "cd '${remote_dir}' && ./deploy.sh"
