#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")"
[[ -f .env ]] || { echo 'Missing .env; run ./setup.sh first.' >&2; exit 1; }
if ! grep -qE '^SITE_ADDRESS=.+' .env; then
  echo 'Warning: SITE_ADDRESS is not set in .env, so the site is served over plain HTTP on port 80.' >&2
  echo '         Add SITE_ADDRESS=your.domain to .env for automatic HTTPS.' >&2
fi
echo "Building images and restarting containers…"
docker compose up -d --build
echo "Waiting for the API to become healthy…"
docker compose ps
for _ in $(seq 1 30); do
  if docker compose exec -T api python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/health')" 2>/dev/null; then
    echo 'LedgerVault deployed and healthy.'
    exit 0
  fi
  sleep 2
done
echo 'API did not become healthy; check: docker compose logs api' >&2
exit 1
