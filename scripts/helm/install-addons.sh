#!/usr/bin/env bash
# Installs the two cluster add-ons Terraform deliberately leaves out. Run once per cluster, after `terraform apply`.
#
#   scripts/helm/install-addons.sh dev          (kubectl must already point at the cluster: terraform output kubeconfig_command)
#
# Chart versions are pinned. The load balancer controller's chart version equals the version of the IAM policy vendored in
# terraform/modules/eks/policies: change them together.
set -euo pipefail

ENVIRONMENT="${1:?usage: install-addons.sh <dev|stage|prod>}"
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
LBC_CHART_VERSION="3.6.1"
METRICS_SERVER_CHART_VERSION="3.14.0"
TF="$ROOT/terraform/environments/$ENVIRONMENT"

CLUSTER="$(terraform -chdir="$TF" output -raw eks_cluster_name)"
VPC_ID="$(terraform -chdir="$TF" output -raw vpc_id)"
REGION="$(terraform -chdir="$TF" output -raw aws_region)"

helm repo add eks https://aws.github.io/eks-charts >/dev/null
helm repo add metrics-server https://kubernetes-sigs.github.io/metrics-server/ >/dev/null
helm repo update >/dev/null

helm upgrade --install aws-load-balancer-controller eks/aws-load-balancer-controller \
  --namespace kube-system --version "$LBC_CHART_VERSION" --wait \
  -f "$ROOT/helm/addons/aws-load-balancer-controller.yaml" \
  --set clusterName="$CLUSTER" --set region="$REGION" --set vpcId="$VPC_ID"

helm upgrade --install metrics-server metrics-server/metrics-server \
  --namespace kube-system --version "$METRICS_SERVER_CHART_VERSION" --wait \
  -f "$ROOT/helm/addons/metrics-server.yaml"

kubectl -n kube-system rollout status deploy/aws-load-balancer-controller deploy/metrics-server
kubectl top nodes   # works only once metrics-server is serving: proves the autoscaler's data source
