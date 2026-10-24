#!/usr/bin/env bash
# Applies database migrations (alembic upgrade head) for the given services, as each service's MIGRATOR role.
# In Kubernetes the same command runs as a Job before the new app version starts (Argo CD pre-sync hook).
#
# Usage:  scripts/db/migrate.sh [service ...]      (default: all six services)
# Connection: DB_HOST DB_PORT DB_NAME (defaults: localhost 5432 school). Passwords: .dev-secrets/db.env
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
SECRETS_FILE="${DB_SECRETS_FILE:-$ROOT/.dev-secrets/db.env}"
[[ -f "$SECRETS_FILE" ]] && { set -a; source "$SECRETS_FILE"; set +a; }
PYTHON="${PYTHON:-$ROOT/services/admission/.venv/bin/python}"
SERVICES=("$@"); [[ ${#SERVICES[@]} -eq 0 ]] && SERVICES=(admission student fee attendance notification auth)

for svc in "${SERVICES[@]}"; do
  upper="$(echo "$svc" | tr '[:lower:]' '[:upper:]')"; pw="${upper}_MIGRATOR_PASSWORD"
  echo "== migrating $svc"
  (cd "$ROOT/services/$svc" && DB_HOST="${DB_HOST:-localhost}" DB_PORT="${DB_PORT:-5432}" DB_NAME="${DB_NAME:-school}" \
     DB_USER="${svc}_migrator" DB_PASSWORD="${!pw}" "$PYTHON" -m alembic upgrade head)
done
