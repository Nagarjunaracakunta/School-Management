import importlib.util
import json
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
spec = importlib.util.spec_from_file_location("changed", ROOT / "scripts/ci/changed.py")
changed = importlib.util.module_from_spec(spec)
spec.loader.exec_module(changed)

ALL_SERVICES = ["auth", "admission", "student", "fee", "attendance", "notification"]


def test_a_change_inside_one_service_runs_only_that_service():
    r = changed.classify(["services/fee/app/services/fee_service.py", "services/fee/tests/conftest.py"])
    assert r["services"] == ["fee"] and not any(r[k] for k in ("frontend", "terraform", "helm", "lambdas", "tools", "workflows"))


def test_the_image_list_names_what_to_build_and_how():
    r = changed.classify(["services/fee/x.py", "tools/db-bootstrap/bootstrap.py"])
    assert r["images"] == [
        {"name": "fee", "context": "services/fee", "dockerfile": "docker/python-service.Dockerfile"},
        {"name": "db-tools", "context": "tools/db-bootstrap", "dockerfile": "docker/db-tools.Dockerfile"},
    ]
    assert changed.classify(["frontend/x.js"])["images"] == []


def test_every_image_name_is_a_repository_terraform_creates():
    """ECR repositories come from terraform/environments/dev/locals.tf: a name missing there would fail the push."""
    import re

    text = (ROOT / "terraform/environments/dev/locals.tf").read_text()
    services = re.search(r"services\s*=\s*\[(.*?)\]", text, re.S).group(1).replace('"', "").replace(" ", "").replace("\n", "").strip(",").split(",")
    repositories = set(services) | {"db-tools"}
    assert {i["name"] for i in changed.everything()["images"]} == repositories


def test_services_come_out_in_a_stable_order():
    assert changed.classify(["services/student/x.py", "services/auth/y.py"])["services"] == ["auth", "student"]


@pytest.mark.parametrize(
    "path",
    ["docker/python-service.Dockerfile", "docker/python-service.Dockerfile.dockerignore", ".github/workflows/_service.yml", "scripts/ci/changed.py"],
)
def test_files_every_service_depends_on_trigger_all_services(path):
    assert changed.classify([path])["services"] == ALL_SERVICES


@pytest.mark.parametrize(
    ("path", "flag"),
    [
        ("frontend/src/App.jsx", "frontend"),
        ("terraform/modules/vpc/main.tf", "terraform"),
        ("scripts/tf/check.sh", "terraform"),
        ("helm/school-service/templates/deployment.yaml", "helm"),
        ("scripts/helm/render-env-values.py", "helm"),
        ("lambdas/notification_delivery/handler.py", "lambdas"),
        ("tools/db-bootstrap/bootstrap.py", "tools"),
        ("docker/db-tools.Dockerfile", "tools"),
        (".github/workflows/ci.yml", "workflows"),
    ],
)
def test_each_area_sets_its_own_flag_only(path, flag):
    r = changed.classify([path])
    assert r[flag] is True
    assert [k for k in ("frontend", "terraform", "helm", "lambdas", "tools", "workflows") if r[k]] == [flag]
    assert r["services"] == []


def test_the_helm_tests_re_run_when_the_terraform_service_list_changes():
    r = changed.classify(["terraform/environments/dev/locals.tf"])
    assert r["terraform"] and r["helm"], "the Helm contract tests read terraform/environments/dev/locals.tf"


def test_documentation_alone_runs_nothing():
    r = changed.classify(["README.md", "docs/helm.md", "docs/adr/0009-ci.md"])
    assert r["services"] == [] and not any(r[k] for k in ("frontend", "terraform", "helm", "lambdas", "tools", "workflows"))


def test_an_unknown_service_folder_is_not_mistaken_for_a_service():
    assert changed.classify(["services/billing/x.py", "services/README.md"])["services"] == []


# ---- against a real git repository -----------------------------------------------------------------------------------------------
def git(repo, *args):
    return subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True, check=True).stdout.strip()


@pytest.fixture
def repo(tmp_path, monkeypatch):
    git(tmp_path, "init", "-q", "-b", "main")
    git(tmp_path, "config", "user.email", "ci@example.com")
    git(tmp_path, "config", "user.name", "ci")
    monkeypatch.chdir(tmp_path)

    def commit(*files):
        for f in files:
            p = tmp_path / f
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(p.read_text() + "x" if p.exists() else "x")
        git(tmp_path, "add", "-A")
        git(tmp_path, "commit", "-q", "-m", "change")
        return git(tmp_path, "rev-parse", "HEAD")

    return commit


def test_it_compares_two_real_commits(repo):
    base = repo("services/fee/a.py", "frontend/a.js")
    head = repo("services/student/b.py")
    result = changed.compute(base, head)
    assert result["services"] == ["student"] and result["frontend"] is False


def test_a_pull_request_branch_is_compared_with_where_it_forked(repo):
    base = repo("services/fee/a.py")
    git(Path.cwd(), "checkout", "-q", "-b", "feature")
    repo("services/auth/x.py")
    head = git(Path.cwd(), "rev-parse", "HEAD")
    git(Path.cwd(), "checkout", "-q", "main")
    repo("services/notification/y.py")  # main moved on meanwhile: must not count as OUR change
    assert changed.compute(base, head)["services"] == ["auth"]


@pytest.mark.parametrize("base", ["", changed.ZERO_SHA, "deadbeef" * 5])
def test_when_the_base_is_unknown_everything_runs(repo, base):
    repo("services/fee/a.py")
    result = changed.compute(base, "HEAD")
    assert result["services"] == ALL_SERVICES and all(result[k] for k in ("frontend", "terraform", "helm", "lambdas", "tools", "workflows"))


def test_github_output_format(repo, tmp_path, monkeypatch, capsys):
    base = repo("services/fee/a.py")
    head = repo("services/student/b.py", "helm/x.yaml")
    out = tmp_path / "gh_output"
    monkeypatch.setenv("GITHUB_OUTPUT", str(out))
    assert changed.main(["--base", base, "--head", head, "--github-output"]) == 0
    lines = dict(line.split("=", 1) for line in out.read_text().splitlines())
    assert json.loads(lines["services"]) == ["student"]
    assert json.loads(lines["images"])[0]["name"] == "student"
    assert lines["helm"] == "true" and lines["frontend"] == "false"  # lower-case strings, as the Actions expression language expects


def test_github_output_needs_the_variable(repo, monkeypatch):
    repo("services/fee/a.py")
    monkeypatch.delenv("GITHUB_OUTPUT", raising=False)
    with pytest.raises(SystemExit, match="GITHUB_OUTPUT"):
        changed.main(["--all", "--github-output"])


def test_all_flag_forces_everything_even_with_a_perfect_diff(repo, capsys):
    base = repo("README.md")
    head = repo("README.md")
    changed.main(["--base", base, "--head", head, "--all"])
    assert json.loads(capsys.readouterr().out)["services"] == ALL_SERVICES
