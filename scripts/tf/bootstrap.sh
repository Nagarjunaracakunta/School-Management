#!/usr/bin/env bash
# Creates (or updates) the Terraform state bucket for ONE AWS account. Run once per account: dev, stage, prod.
#
#   AWS_PROFILE=school-dev scripts/tf/bootstrap.sh dev plan
#   AWS_PROFILE=school-dev scripts/tf/bootstrap.sh dev apply
#
# Your AWS credentials must belong to the account named in terraform/bootstrap/envs/<env>.tfvars (Terraform checks).
set -euo pipefail

ENV="${1:?usage: bootstrap.sh <dev|stage|prod> <plan|apply>}"
ACTION="${2:?usage: bootstrap.sh <dev|stage|prod> <plan|apply>}"
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../terraform/bootstrap" && pwd)"

mkdir -p "$DIR/state"
terraform -chdir="$DIR" init -reconfigure -backend-config="path=state/${ENV}.tfstate"
terraform -chdir="$DIR" "$ACTION" -var-file="envs/${ENV}.tfvars"

if [[ "$ACTION" == "apply" ]]; then
  echo
  echo "Put this into terraform/environments/${ENV}/backend.hcl:"
  terraform -chdir="$DIR" output -raw backend_hcl
fi
