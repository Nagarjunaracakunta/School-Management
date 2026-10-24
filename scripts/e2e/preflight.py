#!/usr/bin/env python3
"""Answers one question: "is it safe to run the next deployment step?" It refuses while placeholder values remain.

    scripts/e2e/preflight.py --env dev --phase pre-apply     # before 'terraform apply'
    scripts/e2e/preflight.py --env dev --phase pre-deploy    # before Argo CD deploys the services
    scripts/e2e/preflight.py --tools                         # are the command-line tools installed?
    scripts/e2e/preflight.py --env dev --phase pre-apply --report   # list instead of failing (used by the dry run)

pre-apply   account ids, repository name, your address, admin role, owners: things YOU know
pre-deploy  things only a real apply or build produces: Terraform-generated Helm values, and image tags that exist in ECR
"""

import argparse
import re
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ACCOUNTS = r"(111111111111|222222222222|333333333333)"

# (phase, file template, regex that means "still a placeholder", what to do)
CHECKS = [
    ("pre-apply", "terraform/environments/{env}/terraform.tfvars", r"allowed_account_ids\s*=\s*\[\"" + ACCOUNTS, "put this environment's real AWS account id (scripts/e2e/configure.py)"),
    ("pre-apply", "terraform/environments/{env}/terraform.tfvars", r"eks_public_access_cidrs\s*=\s*\[\"203\.0\.113\.", "put your public address (configure.py --my-ip)"),
    ("pre-apply", "terraform/environments/{env}/terraform.tfvars", r"eks_admin_principal_arns\s*=\s*\[[^\]]*" + ACCOUNTS, "put a real IAM role ARN (configure.py --admin-role-arn)"),
    ("pre-apply", "terraform/environments/{env}/terraform.tfvars", r"github_repository\s*=\s*\"OWNER/", "put your GitHub owner (configure.py --github-owner)"),
    ("pre-apply", "terraform/environments/{env}/terraform.tfvars", r"ecr_owner_account_id\s*=\s*\"" + ACCOUNTS, "the dev account id (configure.py --dev-account)"),
    ("pre-apply", "terraform/environments/{env}/backend.hcl", ACCOUNTS, "run scripts/tf/bootstrap.sh and paste the printed backend settings"),
    ("pre-apply", "terraform/bootstrap/envs/{env}.tfvars", ACCOUNTS, "put this environment's real AWS account id"),
    ("pre-apply", "argocd/envs/{env}/bootstrap/root.yaml", r"/OWNER/", "scripts/argocd/render_apps.py --repo-url <your repository>"),
    ("pre-apply", ".github/CODEOWNERS", r"@your-github-username", "put your GitHub handle or team"),
    ("pre-deploy", "helm/environments/{env}/common.yaml", ACCOUNTS + "|AbCdEf|GhIjKl", "generate from Terraform: scripts/helm/render-env-values.py"),
    ("pre-deploy", "helm/environments/{env}/*.yaml", r"tag:\s*\"0000000\"", "CI writes real tags: build-images.yml, then update-deployment.yml"),
]
TOOLS = [
    ("git", True), ("python3", True), ("node", True), ("npm", True), ("terraform", True), ("aws", True),
    ("kubectl", True), ("helm", True), ("docker", False), ("gh", False), ("argocd", False), ("jf", False),
]


def scan(env: str, phase: str) -> list[str]:
    problems = []
    for check_phase, template, pattern, advice in CHECKS:
        if check_phase != phase:
            continue
        for path in sorted(ROOT.glob(template.format(env=env))):
            for number, line in enumerate(path.read_text().splitlines(), 1):
                if line.lstrip().startswith("#"):
                    continue  # comments may mention the placeholder while explaining it
                if re.search(pattern, line):
                    problems.append(f"{path.relative_to(ROOT)}:{number}: {line.strip()[:90]}\n      -> {advice}")
    return problems


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--env", choices=["dev", "stage", "prod"])
    p.add_argument("--phase", choices=["pre-apply", "pre-deploy"])
    p.add_argument("--tools", action="store_true")
    p.add_argument("--report", action="store_true", help="print the findings but exit 0")
    a = p.parse_args(argv)
    if not a.tools and not (a.env and a.phase):
        p.error("give --env and --phase, or --tools")

    bad = 0
    if a.tools:
        for tool, required in TOOLS:
            found = shutil.which(tool)
            print(f"  {'ok     ' if found else ('MISSING' if required else 'missing')}  {tool}{'' if found or required else '  (optional)'}")
            bad += 0 if found or not required else 1
    if a.env and a.phase:
        problems = scan(a.env, a.phase)
        print(f"{a.env} / {a.phase}: " + ("no placeholders left" if not problems else f"{len(problems)} placeholder(s) left"))
        for problem in problems:
            print("  " + problem)
        bad += len(problems)
    return 0 if (a.report or bad == 0) else 1


if __name__ == "__main__":
    sys.exit(main())
