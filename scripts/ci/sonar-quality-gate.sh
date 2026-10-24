#!/usr/bin/env bash
# One-time setup of the quality gate on a SonarQube server, so the rules live in a reviewed file, not in someone's clicks.
#   SONAR_HOST_URL=https://sonar.example.com SONAR_TOKEN=<admin token> scripts/ci/sonar-quality-gate.sh
# The token is read from the environment, never from an argument (arguments show up in `ps` and shell history).
set -euo pipefail
: "${SONAR_HOST_URL:?}" "${SONAR_TOKEN:?}"
GATE="school-gate"
api() { curl -fsS -u "${SONAR_TOKEN}:" "$@"; }

api -X POST "$SONAR_HOST_URL/api/qualitygates/create" -d "name=$GATE" >/dev/null || echo "gate $GATE already exists"
# Conditions apply to NEW code only (a "clean as you code" gate): old debt does not block today's work.
add() { api -X POST "$SONAR_HOST_URL/api/qualitygates/create_condition" -d "gateName=$GATE" -d "metric=$1" -d "op=$2" -d "error=$3" >/dev/null || echo "condition on $1 exists"; }
add new_coverage LT 80                    # new code needs 80% test coverage
add new_violations GT 0                   # no new issues of any kind
add new_security_hotspots_reviewed LT 100 # every new security hotspot reviewed
add new_duplicated_lines_density GT 3     # at most 3% copy-paste in new code
api -X POST "$SONAR_HOST_URL/api/qualitygates/select" -d "projectKey=school-management" -d "gateName=$GATE" >/dev/null
echo "quality gate $GATE applied to school-management"
