#!/usr/bin/env bash
# Installs Argo CD into the cluster kubectl currently points at, then hands it the environment's configuration.
#   scripts/argocd/install.sh dev
# Run it ONCE per cluster. After that, Argo CD manages itself less and the applications completely: you change Git, not the cluster.
set -euo pipefail
env="${1:?usage: install.sh dev|stage|prod}"
[[ "$env" =~ ^(dev|stage|prod)$ ]] || { echo "environment must be dev, stage or prod" >&2; exit 1; }
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
CHART_VERSION="10.11.1"

context="$(kubectl config current-context)"
echo "cluster: $context"
[[ "$context" == *"school-$env"* ]] || { echo "refusing: the current kubectl context does not look like school-$env. Run: aws eks update-kubeconfig --name school-$env" >&2; exit 1; }

helm repo add argo https://argoproj.github.io/argo-helm >/dev/null
helm repo update argo >/dev/null
helm upgrade --install argocd argo/argo-cd --version "$CHART_VERSION" \
  --namespace argocd --create-namespace -f "$ROOT/argocd/install/values.yaml" --wait --timeout 10m

kubectl apply -f "$ROOT/argocd/envs/$env/bootstrap/project.yaml"
kubectl apply -f "$ROOT/argocd/envs/$env/bootstrap/root.yaml"
echo
echo "Done. Watch it deploy:   kubectl -n argocd get applications -w"
echo "Open the UI:             kubectl -n argocd port-forward svc/argocd-server 8080:443   (https://localhost:8080)"
echo "First admin password:    kubectl -n argocd get secret argocd-initial-admin-secret -o jsonpath='{.data.password}' | base64 -d"
