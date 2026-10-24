"""The tests build a tiny repository of their own, full of placeholders, so they keep passing after the real repository has been
configured with real account ids."""

import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]

TFVARS = """allowed_account_ids = ["111111111111"]
ecr_pull_account_ids = ["222222222222", "333333333333"]
# a comment may mention allowed_account_ids = ["111111111111"] while explaining it
eks_public_access_cidrs = ["203.0.113.7/32"]
eks_admin_principal_arns = ["arn:aws:iam::111111111111:role/PlatformAdmins"]
github_repository = "OWNER/school-management"
"""


@pytest.fixture
def repo(tmp_path):
    for script in ("e2e/preflight.py", "e2e/configure.py", "argocd/render_apps.py"):
        target = tmp_path / "scripts" / script
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(ROOT / "scripts" / script, target)
    files = {
        "terraform/environments/dev/terraform.tfvars": TFVARS,
        "terraform/environments/dev/backend.hcl": 'bucket = "school-tfstate-111111111111-ap-south-1"\n',
        "terraform/bootstrap/envs/dev.tfvars": 'allowed_account_ids = ["111111111111"]\n',
        "argocd/envs/dev/bootstrap/root.yaml": "    repoURL: https://github.com/OWNER/school-management.git\n",
        ".github/CODEOWNERS": "* @your-github-username\n",
        "helm/environments/dev/common.yaml": 'imageRegistry: "111111111111.dkr.ecr.ap-south-1.amazonaws.com"\n',
        "helm/environments/dev/fee.yaml": 'image:\n  tag: "0000000"\n',
        "terraform/environments/prod/terraform.tfvars": TFVARS.replace("111111111111", "333333333333"),
    }
    for name, text in files.items():
        (tmp_path / name).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / name).write_text(text)
    return tmp_path


def run(repo: Path, script: str, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(repo / "scripts/e2e" / script), *args], capture_output=True, text=True)


GOOD = ["--github-owner", "acme", "--dev-account", "123456789012", "--my-ip", "198.51.100.20",
        "--admin-role-arn", "arn:aws:iam::123456789012:role/PlatformAdmins"]


def test_preflight_refuses_while_placeholders_remain_and_ignores_comments(repo):
    result = run(repo, "preflight.py", "--env", "dev", "--phase", "pre-apply")
    assert result.returncode == 1
    assert "allowed_account_ids" in result.stdout and "CODEOWNERS" in result.stdout
    assert "a comment may mention" not in result.stdout


def test_report_mode_lists_but_does_not_fail(repo):
    assert run(repo, "preflight.py", "--env", "dev", "--phase", "pre-apply", "--report").returncode == 0


def test_generated_helm_values_and_image_tags_are_pre_deploy_work_not_pre_apply_work(repo):
    pre_apply = run(repo, "preflight.py", "--env", "dev", "--phase", "pre-apply").stdout
    pre_deploy = run(repo, "preflight.py", "--env", "dev", "--phase", "pre-deploy").stdout
    assert "common.yaml" not in pre_apply and "common.yaml" in pre_deploy
    assert 'tag: "0000000"' in pre_deploy


def test_configure_clears_every_pre_apply_placeholder_for_dev(repo):
    done = run(repo, "configure.py", *GOOD)
    assert done.returncode == 0, done.stderr
    assert run(repo, "preflight.py", "--env", "dev", "--phase", "pre-apply").returncode == 0
    tfvars = (repo / "terraform/environments/dev/terraform.tfvars").read_text()
    assert '["123456789012"]' in tfvars and "198.51.100.20/32" in tfvars and "acme/school-management" in tfvars
    assert "role/PlatformAdmins" in tfvars and "arn:aws:iam::123456789012:" in tfvars
    assert "https://github.com/acme/school-management.git" in (repo / "argocd/envs/dev/bootstrap/root.yaml").read_text()
    # stage and prod keep their placeholders until they get their own accounts
    assert run(repo, "preflight.py", "--env", "prod", "--phase", "pre-apply").returncode == 1


def test_dry_run_changes_nothing(repo):
    before = (repo / "terraform/environments/dev/terraform.tfvars").read_text()
    assert run(repo, "configure.py", *GOOD, "--dry-run").returncode == 0
    assert (repo / "terraform/environments/dev/terraform.tfvars").read_text() == before


@pytest.mark.parametrize("flag,value", [("--my-ip", "10.0.0.5"), ("--my-ip", "not-an-ip"), ("--dev-account", "123"), ("--admin-role-arn", "role/x"), ("--github-owner", "bad owner!")])
def test_configure_refuses_values_that_would_break_the_deployment(repo, flag, value):
    args = list(GOOD)
    args[args.index(flag) + 1] = value
    assert run(repo, "configure.py", *args, "--dry-run").returncode != 0
