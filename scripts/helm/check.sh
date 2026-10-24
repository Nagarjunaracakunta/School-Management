#!/usr/bin/env bash
# Everything about the Helm charts that can be checked WITHOUT a cluster: lint, render every service in every environment,
# validate the result against the Kubernetes API schemas, and run the property tests. CI runs exactly this (Phase 16).
#
#   HELM_BIN=/path/to/helm KUBECONFORM_BIN=/path/to/kubeconform scripts/helm/check.sh
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT/helm"
HELM="${HELM_BIN:-helm}"; KUBECONFORM="${KUBECONFORM_BIN:-kubeconform}"
K8S_VERSION="${K8S_VERSION:-1.34.0}"      # keep equal to the cluster's Kubernetes version (terraform: kubernetes_version)
SERVICES=(auth admission student fee attendance notification)
fail=0

for env in dev stage prod; do
  echo "== school-platform / $env"
  $HELM lint school-platform -f "environments/$env/common.yaml" -f "environments/$env/platform.yaml" >/dev/null || fail=1
  $HELM template school-platform school-platform -n "school-$env" -f "environments/$env/common.yaml" -f "environments/$env/platform.yaml" \
    | $KUBECONFORM -strict -kubernetes-version "$K8S_VERSION" -summary - | tail -1 | grep -q "Invalid: 0, Errors: 0" || { echo "  INVALID"; fail=1; }
  for svc in "${SERVICES[@]}"; do
    args=(-f "services/$svc.yaml" -f "environments/$env/common.yaml" -f "environments/$env/$svc.yaml")
    $HELM lint school-service "${args[@]}" >/dev/null || { echo "  lint failed: $env/$svc"; fail=1; }
    $HELM template "$svc" school-service -n "school-$env" "${args[@]}" \
      | $KUBECONFORM -strict -kubernetes-version "$K8S_VERSION" -summary - | tail -1 | grep -q "Invalid: 0, Errors: 0" || { echo "  INVALID: $env/$svc"; fail=1; }
  done
done

echo "== property tests (security, routing, contracts with Terraform)"
HELM_BIN="$HELM" python3 -m pytest "$ROOT/helm/tests" -q -p no:cacheprovider || fail=1

[[ $fail -eq 0 ]] && echo "ALL HELM CHECKS PASSED" || { echo "HELM CHECKS FAILED"; exit 1; }
