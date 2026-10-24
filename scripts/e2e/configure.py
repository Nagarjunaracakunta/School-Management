#!/usr/bin/env python3
"""Replaces the placeholder values in the repository with your real ones, in one reviewable step.

    scripts/e2e/configure.py --github-owner acme --dev-account 123456789012 --my-ip 198.51.100.20 \\
        --admin-role-arn arn:aws:iam::123456789012:role/PlatformAdmins [--dry-run]
    (add --stage-account / --prod-account when those environments get their own AWS accounts)

What it changes (nothing else is touched):
  account ids           terraform/environments/*/terraform.tfvars, terraform/bootstrap/envs/*.tfvars, backend.hcl
  your GitHub owner     OWNER/school-management in the tfvars and the Argo CD files; @your-github-username in CODEOWNERS
  your public address   the only address allowed to reach the Kubernetes API (kubectl) from the internet
  cluster admin role    the IAM role that is Kubernetes cluster-admin
Run it, read `git diff`, commit. Run `scripts/e2e/preflight.py --env dev --phase pre-apply` afterwards.
"""

import argparse
import ipaddress
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PLACEHOLDER_ACCOUNT = {"dev": "111111111111", "stage": "222222222222", "prod": "333333333333"}
ADMIN_ROLE = re.compile(r'arn:aws:iam::\d{12}:role/PlatformAdmins')


def files_for(env: str) -> list[Path]:
    return [
        ROOT / f"terraform/environments/{env}/terraform.tfvars",
        ROOT / f"terraform/environments/{env}/backend.hcl",
        ROOT / f"terraform/bootstrap/envs/{env}.tfvars",
    ]


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--github-owner", required=True, help="your GitHub user or organisation")
    p.add_argument("--repo", default="school-management", help="the repository name")
    p.add_argument("--dev-account", required=True)
    p.add_argument("--stage-account")
    p.add_argument("--prod-account")
    p.add_argument("--my-ip", required=True, help="the public address of the machine you run kubectl from (see https://checkip.amazonaws.com)")
    p.add_argument("--admin-role-arn", required=True, help="IAM role that becomes cluster-admin (assumed through SSO, not a person's key)")
    p.add_argument("--dry-run", action="store_true")
    a = p.parse_args(argv)

    accounts = {"dev": a.dev_account, "stage": a.stage_account, "prod": a.prod_account}
    for env, acct in accounts.items():
        if acct and not re.fullmatch(r"\d{12}", acct):
            sys.exit(f"--{env}-account must be 12 digits")
    if not re.fullmatch(r"arn:aws:iam::\d{12}:role/[\w+=,.@/-]+", a.admin_role_arn):
        sys.exit("--admin-role-arn must look like arn:aws:iam::<12 digits>:role/<name>")
    ip = ipaddress.ip_address(a.my_ip)  # raises on garbage
    rfc1918 = [ipaddress.ip_network(n) for n in ("10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16")]
    if ip.is_loopback or ip.is_link_local or any(ip in n for n in rfc1918):
        sys.exit(f"{ip} is a private address: use your PUBLIC address (https://checkip.amazonaws.com)")
    if not re.fullmatch(r"[A-Za-z0-9-]+", a.github_owner):
        sys.exit("--github-owner may contain only letters, digits and hyphens")

    changed: list[str] = []

    def rewrite(path: Path, transform) -> None:
        if not path.exists():
            return
        before = path.read_text()
        after = transform(before)
        if after != before:
            changed.append(str(path.relative_to(ROOT)))
            if not a.dry_run:
                path.write_text(after)

    for env in ("dev", "stage", "prod"):
        def transform(text: str, env=env) -> str:
            for e, acct in accounts.items():
                if acct:
                    text = text.replace(PLACEHOLDER_ACCOUNT[e], acct)
            text = text.replace("OWNER/school-management", f"{a.github_owner}/{a.repo}")
            text = text.replace("203.0.113.7/32", f"{a.my_ip}/32")
            if accounts[env] and env_file_is_tfvars:
                role = re.sub(r"arn:aws:iam::\d{12}:", f"arn:aws:iam::{accounts[env]}:", a.admin_role_arn)
                text = ADMIN_ROLE.sub(role, text)
            return text

        for f in files_for(env):
            env_file_is_tfvars = f.name == "terraform.tfvars"
            rewrite(f, transform)

    rewrite(ROOT / ".github/CODEOWNERS", lambda t: t.replace("@your-github-username", f"@{a.github_owner}"))

    repo_url = f"https://github.com/{a.github_owner}/{a.repo}.git"
    if not a.dry_run:
        subprocess.run([sys.executable, str(ROOT / "scripts/argocd/render_apps.py"), "--repo-url", repo_url], check=True)
        changed.append("argocd/envs/** (regenerated)")
    print(("would change" if a.dry_run else "changed") + ":\n  " + "\n  ".join(sorted(set(changed))))
    print("\nnext: git diff   (read it), then scripts/e2e/preflight.py --env dev --phase pre-apply")
    return 0


if __name__ == "__main__":
    sys.exit(main())
