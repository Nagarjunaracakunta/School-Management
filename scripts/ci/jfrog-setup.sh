#!/usr/bin/env bash
# One-time creation of the Artifactory repositories described in jfrog/*.json (so they are reviewed like code).
#   JF_URL=https://acme.jfrog.io JF_ADMIN_TOKEN=<admin token> scripts/ci/jfrog-setup.sh
# The token is read from the environment, never from an argument (arguments show up in `ps` and shell history).
set -euo pipefail
: "${JF_URL:?}" "${JF_ADMIN_TOKEN:?}"
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
# Remote repositories first: a virtual repository can only include repositories that already exist.
for kind in local remote virtual; do
  for f in "$ROOT"/jfrog/*.json; do
    [[ $(python3 -c "import json,sys;print(json.load(open(sys.argv[1]))['rclass'])" "$f") == "$kind" ]] || continue
    key=$(basename "$f" .json)
    code=$(curl -sS -o /dev/null -w '%{http_code}' -X PUT -H "Authorization: Bearer ${JF_ADMIN_TOKEN}" \
           -H 'Content-Type: application/json' --data @"$f" "$JF_URL/artifactory/api/repositories/$key")
    case "$code" in 200|201) echo "ok       $key" ;; 400) echo "exists   $key (HTTP 400: already there or invalid; check the UI)" ;; *) echo "FAILED   $key (HTTP $code)"; exit 1 ;; esac
  done
done
