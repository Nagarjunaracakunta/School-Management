#!/usr/bin/env bash
# CloudFront must know the address of the load balancer, but that address only exists after Argo CD has deployed the services
# (the Kubernetes Ingress creates the load balancer). So the first Terraform apply builds the website WITHOUT the API route, and
# this script closes the loop:
#
#   scripts/e2e/set-api-origin.sh dev            # reads the address from the cluster, writes it into terraform.tfvars
#   terraform -chdir=terraform/environments/dev apply -var-file=terraform.tfvars      # CloudFront now forwards /api/* to it
#
# With api_origin_protocol = "https" the name must be one that your certificate covers (a DNS name you own pointing at the load
# balancer): pass it as the second argument instead of reading it from the cluster.
set -euo pipefail

env="${1:?usage: set-api-origin.sh dev|stage|prod [dns-name]}"
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
TFVARS="$ROOT/terraform/environments/$env/terraform.tfvars"
[[ -f "$TFVARS" ]] || { echo "no $TFVARS" >&2; exit 1; }

if [[ -n "${2:-}" ]]; then
  host="$2"
else
  host="$(kubectl -n "school-$env" get ingress -o jsonpath='{.items[0].status.loadBalancer.ingress[0].hostname}' 2>/dev/null || true)"
  [[ -n "$host" ]] || { echo "the Ingress has no address yet. Is Argo CD finished?  kubectl -n school-$env get ingress" >&2; exit 1; }
fi
[[ "$host" =~ ^[A-Za-z0-9]([A-Za-z0-9.-]*[A-Za-z0-9])?$ ]] || { echo "not a host name: $host" >&2; exit 1; }

python3 - "$TFVARS" "$host" <<'PY'
import re, sys
path, host = sys.argv[1], sys.argv[2]
text = open(path).read()
line = f'api_origin_domain_name = "{host}"'
if re.search(r"^api_origin_domain_name\s*=.*$", text, re.M):
    text = re.sub(r"^api_origin_domain_name\s*=.*$", line, text, flags=re.M)
else:
    text = text.rstrip("\n") + f"\n\n# set by scripts/e2e/set-api-origin.sh: the load balancer that serves /api/*\n{line}\n"
open(path, "w").write(text)
PY
echo "wrote api_origin_domain_name = \"$host\" to terraform/environments/$env/terraform.tfvars"
echo "next: terraform -chdir=terraform/environments/$env apply -var-file=terraform.tfvars   (then commit the file)"
