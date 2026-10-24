#!/usr/bin/env bash
# Run SonarQube on your laptop and analyse this repository with it.
#   scripts/ci/sonar-local.sh start | stop | scan <token>
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT"
ENV_FILE=".dev-secrets/sonar.env"
compose() { docker compose -f docker-compose.sonar.yml --env-file "$ENV_FILE" "$@"; }

case "${1:-}" in
  start)
    mkdir -p .dev-secrets
    [[ -f $ENV_FILE ]] || { umask 077; echo "SONAR_DB_PASSWORD=$(openssl rand -hex 16)" > "$ENV_FILE"; }
    compose up -d
    echo "SonarQube is starting (about 2 minutes): http://localhost:9000   first login admin / admin"
    ;;
  stop) compose down ;;
  scan)
    token="${2:?usage: sonar-local.sh scan <token>   (create one in SonarQube: My Account > Security)}"
    # 1. coverage for every service (fast SQLite mode), with file names SonarQube understands
    for s in auth admission student fee attendance notification; do
      (cd "services/$s" && python3 -m pytest -q -p no:cacheprovider >/dev/null)
      python3 scripts/ci/prefix_coverage.py "services/$s/coverage.xml" "services/$s/app"
    done
    (cd frontend && npm run test:coverage >/dev/null)
    # 2. the scanner runs in a container and reaches SonarQube through the host
    docker run --rm -e SONAR_TOKEN="$token" -e SONAR_HOST_URL="http://host.docker.internal:9000" \
      -v "$ROOT:/usr/src" sonarsource/sonar-scanner-cli
    ;;
  *) sed -n 2,3p "$0"; exit 1 ;;
esac
