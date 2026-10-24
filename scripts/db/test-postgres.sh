#!/usr/bin/env bash
# Runs every service's test suite against a REAL PostgreSQL (the default is in-memory SQLite).
# Each service gets its own schema, so suites cannot disturb each other.
#
# Connection (admin or any role that may create schemas in the test database):
#   PGHOST PGPORT PGUSER PGPASSWORD   and   TEST_DB_NAME (default: school_test)
# Usage: scripts/db/test-postgres.sh [service ...]
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DB="${TEST_DB_NAME:-school_test}"
SERVICES=("$@"); [[ ${#SERVICES[@]} -eq 0 ]] && SERVICES=(admission student fee attendance notification auth)
PYTEST="${PYTEST:-$ROOT/services/admission/.venv/bin/pytest}"

for svc in "${SERVICES[@]}"; do
  PGDATABASE="$DB" psql -q -c "CREATE SCHEMA IF NOT EXISTS ${svc}_test"
  echo "== $svc (PostgreSQL schema ${svc}_test)"
  # The password must be URL-safe; generate throwaway test credentials accordingly.
  url="postgresql+psycopg://${PGUSER}:${PGPASSWORD}@${PGHOST:-localhost}:${PGPORT:-5432}/${DB}?options=-csearch_path%3D${svc}_test"
  (cd "$ROOT/services/$svc" && TEST_DATABASE_URL="$url" "$PYTEST" -q -p no:cacheprovider --no-cov)
done
