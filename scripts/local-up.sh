#!/usr/bin/env bash
# Starts the WHOLE platform locally in Docker and creates the first administrator.
#
#   scripts/local-up.sh                       # prompts for the admin password
#   LOCAL_ADMIN_EMAIL=me@school.example LOCAL_ADMIN_PASSWORD='a long passphrase' scripts/local-up.sh
#   scripts/local-up.sh down                  # stop everything (keeps the data)
#   scripts/local-up.sh reset                 # stop everything AND delete the database
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
"$ROOT/scripts/db/gen-secrets.sh"
"$ROOT/scripts/gen-dev-keys.sh"
dc() { docker compose --env-file .dev-secrets/db.env --profile full "$@"; }

case "${1:-up}" in
  down)  dc down; exit 0 ;;
  reset) dc down -v; exit 0 ;;
esac

dc up -d --build --wait

EMAIL="${LOCAL_ADMIN_EMAIL:-admin@school.example}"
PASSWORD="${LOCAL_ADMIN_PASSWORD:-}"
if [[ -z "$PASSWORD" ]]; then read -rsp "Choose a password for $EMAIL (12+ characters): " PASSWORD; echo; fi

# The password goes in as an environment variable, never as an argument (arguments are visible in process lists).
if out=$(dc run --rm -T -e AUTH_ADMIN_PASSWORD="$PASSWORD" auth python -m app.cli create-admin --email "$EMAIL" --name "Local Admin" 2>&1); then
  echo "created administrator $EMAIL"
elif grep -q "already exists" <<<"$out"; then
  echo "administrator $EMAIL already exists (unchanged)"
else
  echo "$out" >&2; exit 1
fi

echo
echo "Portal:     http://localhost:8080      (log in as $EMAIL)"
echo "Database:   localhost:5432             (passwords in .dev-secrets/db.env)"
echo "Logs:       docker compose --env-file .dev-secrets/db.env --profile full logs -f <service>"
echo "Stop:       scripts/local-up.sh down      Wipe data: scripts/local-up.sh reset"
