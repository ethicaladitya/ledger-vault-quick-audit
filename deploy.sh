#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")"
[[ -f .env ]] || { echo 'Missing .env; run ./setup.sh first.' >&2; exit 1; }
docker compose up -d --build
docker compose ps
curl --fail --silent --show-error --retry 10 --retry-delay 2 http://localhost/api/health >/dev/null
echo 'LedgerVault deployed and healthy.'
