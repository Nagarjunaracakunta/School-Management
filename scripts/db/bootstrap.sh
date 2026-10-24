#!/usr/bin/env bash
# Creates the schemas and roles for every service. Run once per environment as a database administrator.
#
# Connection (standard libpq variables):  PGHOST PGPORT PGUSER PGPASSWORD PGDATABASE
# Passwords, one pair per service:        <SERVICE>_MIGRATOR_PASSWORD  <SERVICE>_APP_PASSWORD
#   - In AWS these come from Secrets Manager (injected by whatever runs this script).
#   - Locally, if they are not set, random ones are generated into .dev-secrets/db.env (git-ignored).
set -euo pipefail

SERVICES=(${SERVICES:-admission student fee attendance notification auth})
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
SECRETS_FILE="${DB_SECRETS_FILE:-$ROOT/.dev-secrets/db.env}"
export PGDATABASE="${PGDATABASE:-school}"

if [[ -f "$SECRETS_FILE" ]]; then set -a; source "$SECRETS_FILE"; set +a; fi

generate_missing_passwords() {
  DB_SECRETS_FILE="$SECRETS_FILE" "$ROOT/scripts/db/gen-secrets.sh"
  set -a; source "$SECRETS_FILE"; set +a
}
[[ "${GENERATE_PASSWORDS:-1}" == "1" ]] && generate_missing_passwords

psql -v ON_ERROR_STOP=1 -q -f "$ROOT/scripts/db/common.sql"
for svc in "${SERVICES[@]}"; do
  upper="$(echo "$svc" | tr '[:lower:]' '[:upper:]')"
  mig="${upper}_MIGRATOR_PASSWORD"; app="${upper}_APP_PASSWORD"
  psql -v ON_ERROR_STOP=1 -q \
    -v schema="$svc" -v migrator="${svc}_migrator" -v app="${svc}_svc" \
    -v migrator_pw="${!mig}" -v app_pw="${!app}" \
    -f "$ROOT/scripts/db/service_roles.sql"
  echo "ready: schema '$svc', roles '${svc}_migrator' and '${svc}_svc'"
done
