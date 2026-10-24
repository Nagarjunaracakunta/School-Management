import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "scripts" / "argocd"))
import render_apps as r  # noqa: E402


def load(path):
    return yaml.safe_load(path.read_text())


APPS = [(env, name) for env in r.ENVIRONMENTS for name, _, _ in r.RELEASES]


def test_committed_files_match_the_generator():
    assert r.main(["--check"]) == 0


@pytest.mark.parametrize("env,name", APPS)
def test_every_values_file_and_chart_an_application_names_exists(env, name):
    app = load(r.OUT / env / "apps" / f"{name}.yaml")
    chart, values = app["spec"]["sources"]
    assert (ROOT / chart["path"] / "Chart.yaml").exists()
    for vf in chart["helm"]["valueFiles"]:
        assert vf.startswith("$values/")
        assert (ROOT / vf.removeprefix("$values/")).exists(), vf
    assert values["ref"] == "values" and values["repoURL"] == chart["repoURL"]


@pytest.mark.parametrize("env,name", APPS)
def test_each_release_uses_the_environments_own_namespace_and_project(env, name):
    spec = load(r.OUT / env / "apps" / f"{name}.yaml")["spec"]
    assert spec["destination"]["namespace"] == f"school-{env}"
    assert spec["project"] == f"school-{env}"
    # the release name is the service name, exactly as in the by-hand install in docs/helm.md
    assert spec["sources"][0]["helm"]["releaseName"] == name


@pytest.mark.parametrize("name", [n for n, _, _ in r.RELEASES])
def test_only_prod_waits_for_a_person_to_press_sync(name):
    for env in ("dev", "stage"):
        assert "automated" in load(r.OUT / env / "apps" / f"{name}.yaml")["spec"]["syncPolicy"]
    prod = load(r.OUT / "prod" / "apps" / f"{name}.yaml")
    assert "automated" not in prod["spec"]["syncPolicy"]
    assert "finalizers" not in prod["metadata"]  # deleting the Application must not delete the running service


def test_the_platform_goes_first_and_creates_the_restricted_namespace():
    waves = {n: w for n, _, w in r.RELEASES}
    assert waves["platform"] == 0 and all(w > 0 for n, w in waves.items() if n != "platform")
    assert waves["auth"] < waves["admission"] and waves["student"] < waves["fee"]
    spec = load(r.OUT / "dev" / "apps" / "platform.yaml")["spec"]["syncPolicy"]
    assert "CreateNamespace=true" in spec["syncOptions"]
    assert spec["managedNamespaceMetadata"]["labels"]["pod-security.kubernetes.io/enforce"] == "restricted"


@pytest.mark.parametrize("env", r.ENVIRONMENTS)
def test_the_project_allows_only_this_repository_this_namespace_and_no_cluster_objects(env):
    proj = load(r.OUT / env / "bootstrap" / "project.yaml")["spec"]
    assert proj["destinations"] == [{"server": r.SERVER, "namespace": f"school-{env}"}]
    assert proj["sourceRepos"] == [r.DEFAULT_REPO]
    assert proj["clusterResourceWhitelist"] == [{"group": "", "kind": "Namespace"}]


@pytest.mark.parametrize("env", r.ENVIRONMENTS)
def test_the_root_application_watches_exactly_the_apps_folder(env):
    root = load(r.OUT / env / "bootstrap" / "root.yaml")["spec"]
    assert root["source"]["path"] == f"argocd/envs/{env}/apps"
    assert (ROOT / root["source"]["path"]).is_dir()


def test_release_names_match_the_helm_values_that_exist():
    for name, chart, _ in r.RELEASES:
        if chart == "school-service":
            assert (ROOT / "helm" / "services" / f"{name}.yaml").exists()
