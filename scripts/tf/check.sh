#!/usr/bin/env bash
# Everything that can be checked WITHOUT an AWS account: formatting, validation, the three environments being in
# step with each other, and the offline tests. CI runs exactly this (Phase 16).
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT/terraform"
export TF_PLUGIN_CACHE_DIR="${TF_PLUGIN_CACHE_DIR:-$HOME/.terraform.d/plugin-cache}"   # download the big AWS provider once
mkdir -p "$TF_PLUGIN_CACHE_DIR"
export TF_IN_AUTOMATION=1
fail=0

echo "== formatting"
terraform fmt -check -recursive || { echo "run: terraform fmt -recursive"; fail=1; }

echo "== the three environments must differ only in backend.tf, backend.hcl and terraform.tfvars"
for f in $(cd environments/dev && ls *.tf tests/*.tftest.hcl | grep -v '^backend.tf$'); do
  for e in stage prod; do
    cmp -s "environments/dev/$f" "environments/$e/$f" || { echo "DRIFT: environments/$e/$f differs from dev"; fail=1; }
  done
done
for e in stage prod; do   # and no environment may have an extra .tf file the others lack
  diff <(cd environments/dev && ls *.tf) <(cd environments/$e && ls *.tf) >/dev/null || { echo "DRIFT: environments/$e has a different set of .tf files than dev"; fail=1; }
done

echo "== provider lock files: same versions and hashes everywhere, both platforms covered"
python3 "$ROOT/scripts/tf/check_locks.py" || fail=1

run_in() {  # run_in <dir> <label> <terraform args...>
  local dir="$1" label="$2"; shift 2
  echo "== $label"
  ( cd "$dir" && terraform init -backend=false -input=false >/dev/null && terraform validate -no-color >/dev/null && terraform test -no-color "$@" ) || fail=1
}
run_in bootstrap "bootstrap"
for m in modules/*/; do ls "$m"*.tf >/dev/null 2>&1 && run_in "${m%/}" "module $(basename "$m")"; done  # skip placeholders with no code yet
for e in dev stage prod; do run_in "environments/$e" "environment $e" -var-file=terraform.tfvars; done

[[ $fail -eq 0 ]] && echo "ALL TERRAFORM CHECKS PASSED" || { echo "TERRAFORM CHECKS FAILED"; exit 1; }
