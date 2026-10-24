#!/usr/bin/env bash
# The DRY RUN: everything that can be proven WITHOUT an AWS account, in one command, with a pass/fail table at the end.
#
#   scripts/e2e/dry-run.sh                # all offline checks (about 5 minutes the first time)
#   scripts/e2e/dry-run.sh --with-stack   # also start the platform natively and run the end-to-end smoke test
#
# Not covered, because it needs a real account: terraform apply, ECR pushes, EKS, Argo CD syncing, CloudFront. Those are the steps
# in docs/deployment.md, in order. Tools it cannot find (helm, kubeconform, actionlint, gitleaks, docker) are reported as SKIPPED.
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT"
VENV="$ROOT/.venv-e2e"
SERVICES=(auth admission student fee attendance notification)
declare -a RESULTS=()
LOG="$(mktemp -d)"

record() { RESULTS+=("$1|$2|$3"); printf '  %-8s %s\n' "$2" "$1"; }
run() {  # run <label> <command...>
  local label="$1" file; shift
  file="$LOG/${label//[^A-Za-z0-9]/_}.log"
  if "$@" >"$file" 2>&1; then record "$label" PASS ""; else record "$label" FAIL "$file"; fi
}
need() { command -v "$1" >/dev/null 2>&1; }
skip() { record "$1" SKIPPED "$2"; }

echo "== preparing the Python environment"
if [[ ! -x "$VENV/bin/python" ]]; then
  python3 -m venv "$VENV"
  args=(); for s in "${SERVICES[@]}"; do args+=(-r "services/$s/requirements-dev.txt"); done
  "$VENV/bin/pip" install -q --disable-pip-version-check "${args[@]}" "moto[server]==5.2.4" -r tools/db-bootstrap/requirements-dev.txt -r lambdas/notification_delivery/requirements-dev.txt pyyaml
fi
PY="$VENV/bin/python"

echo "== services: lint, tests, coverage floor 85%"
for s in "${SERVICES[@]}"; do
  run "lint $s" bash -c "cd services/$s && $VENV/bin/ruff check app tests migrations && $VENV/bin/ruff format --check app tests migrations"
  run "tests $s" bash -c "cd services/$s && $PY -m pytest -q -p no:cacheprovider --cov-fail-under=85"
done
run "lambda tests" "$PY" -m pytest -q -p no:cacheprovider lambdas/notification_delivery/tests
run "db-bootstrap tests (SQL parts need PostgreSQL)" "$PY" -m pytest -q -p no:cacheprovider tools/db-bootstrap/tests

echo "== frontend"
if need npm; then
  run "frontend tests" bash -c "cd frontend && { [ -d node_modules ] || npm ci --silent; } && npm test"
  run "frontend build" bash -c "cd frontend && npm run build"
else skip "frontend" "npm not installed"; fi

echo "== repository scripts"
run "ci / argocd / e2e script tests" "$PY" -m pytest -q -p no:cacheprovider scripts/ci/tests scripts/argocd/tests scripts/e2e/tests
run "argocd files are what the generator makes" "$PY" scripts/argocd/render_apps.py --check
run "frontend deploy script (dry)" scripts/e2e/deploy-frontend.sh frontend/dist s3-bucket-name EDISTRIBUTION --dry-run

echo "== infrastructure"
if need terraform; then run "terraform fmt/validate/tests" scripts/tf/check.sh; else skip "terraform" "not installed"; fi
if need helm && need kubeconform; then run "helm lint/render/schemas/tests" env HELM_BIN=helm KUBECONFORM_BIN=kubeconform scripts/helm/check.sh
else skip "helm" "helm or kubeconform not installed"; fi

echo "== pipelines and secrets"
if need actionlint; then run "workflow lint (actionlint)" actionlint; else skip "actionlint" "not installed"; fi
if need gitleaks; then run "secret scan (gitleaks, working tree)" gitleaks dir . --redact --no-banner --config .gitleaks.toml
else skip "gitleaks" "not installed"; fi

if [[ "${1:-}" == "--with-stack" ]]; then
  echo "== the whole platform, natively: three business flows + security checks"
  if run "start the platform" scripts/e2e/native-stack.sh start; then
    run "end-to-end smoke test" env SMOKE_EMAIL=admin@school.example SMOKE_PASSWORD="${LOCAL_ADMIN_PASSWORD:-native-stack-passphrase-1}" "$PY" scripts/e2e/smoke.py http://localhost:5173
    scripts/e2e/native-stack.sh stop >/dev/null 2>&1
  fi
else
  skip "end-to-end smoke test" "add --with-stack"
fi

echo "== placeholders still to fill (informational, needs your AWS account)"
"$PY" scripts/e2e/preflight.py --env dev --phase pre-apply --report | head -1
"$PY" scripts/e2e/preflight.py --env dev --phase pre-deploy --report | head -1

echo
echo "================ SUMMARY ================"
fails=0
for r in "${RESULTS[@]}"; do
  IFS='|' read -r label status detail <<<"$r"
  printf '%-8s %s%s\n' "$status" "$label" "${detail:+   ($detail)}"
  [[ "$status" == FAIL ]] && fails=$((fails + 1))
done
[[ $fails -eq 0 ]] && echo "DRY RUN PASSED" || { echo "DRY RUN FAILED: $fails check(s)"; exit 1; }
