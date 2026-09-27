#!/usr/bin/env bash
set -euo pipefail

# Bootstrap a fresh Ubuntu host. Run from the LedgerVault repository as a user
# with sudo access. This installs Docker, creates a private database secret,
# and starts the production compose stack with automatic HTTPS via Caddy.
if ! command -v docker >/dev/null 2>&1; then
  sudo apt-get update
  sudo DEBIAN_FRONTEND=noninteractive apt-get install -y docker.io docker-compose-v2 openssl
  sudo systemctl enable --now docker
  sudo usermod -aG docker "${USER}"
  echo "Docker installed. Log out/in once if the docker group is not active, then rerun ./setup.sh."
  exit 0
fi
if [[ ! -f .env ]]; then
  db_password="$(openssl rand -hex 24)"
  jwt_secret="$(openssl rand -hex 48)"
  umask 077
  printf 'POSTGRES_DB=ledgervault\nPOSTGRES_USER=ledgervault\nPOSTGRES_PASSWORD=%s\nDATABASE_URL=postgresql+psycopg://ledgervault:%s@db:5432/ledgervault\nJWT_SECRET=%s\n' "$db_password" "$db_password" "$jwt_secret" > .env
fi
docker compose up -d --build
docker compose ps
