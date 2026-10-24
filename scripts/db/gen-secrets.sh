#!/usr/bin/env bash
# Generates any missing LOCAL database passwords into .dev-secrets/db.env (git-ignored, mode 600). Safe to re-run:
# existing values are kept. In AWS these values live in Secrets Manager, not in a file.
set -euo pipefail

SERVICES=(${SERVICES:-admission student fee attendance notification auth})
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
SECRETS_FILE="${DB_SECRETS_FILE:-$ROOT/.dev-secrets/db.env}"

mkdir -p "$(dirname "$SECRETS_FILE")"; chmod 700 "$(dirname "$SECRETS_FILE")"
touch "$SECRETS_FILE"; chmod 600 "$SECRETS_FILE"

ensure() {  # ensure VAR_NAME : append a random value unless the file already defines it
  grep -q "^$1=" "$SECRETS_FILE" || { printf '%s=%s\n' "$1" "$(openssl rand -hex 16)" >> "$SECRETS_FILE"; echo "generated $1" >&2; }
}
ensure PG_ADMIN_PASSWORD
for svc in "${SERVICES[@]}"; do
  upper="$(echo "$svc" | tr '[:lower:]' '[:upper:]')"
  ensure "${upper}_MIGRATOR_PASSWORD"; ensure "${upper}_APP_PASSWORD"
done
