"""Renders the chart with `helm template` and checks what matters: that every pod is locked down, that each service gets
only its own secrets, that the load-balancer routes are right, and that the chart matches the Terraform it depends on.

Needs the helm binary (HELM_BIN, or `helm` on PATH). Without it these tests are skipped, not failed.
Run:   HELM_BIN=/path/to/helm pytest helm/tests
"""

import json
import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
# HELM_BIN may be a full path or just a command name ("helm"); either way resolve it on PATH, or the tests would be skipped silently.
_found = shutil.which(os.environ.get("HELM_BIN") or "helm")
HELM = Path(_found) if _found else None
pytestmark = pytest.mark.skipif(not HELM or not Path(HELM).exists(), reason="helm binary not found (set HELM_BIN)")

CHART = ROOT / "helm" / "school-service"
SERVICES = ["auth", "admission", "student", "fee", "attendance", "notification"]
ENVS = ["dev", "stage", "prod"]
HELM_DIR = ROOT / "helm"


class HelmError(Exception):
    pass


def render(service: str, env: str = "dev", *extra: str, sets: dict | None = None) -> list[dict]:
    cmd = [
        str(HELM), "template", service, str(CHART), "-n", f"school-{env}",
        "-f", str(HELM_DIR / "services" / f"{service}.yaml"),
        "-f", str(HELM_DIR / "environments" / env / "common.yaml"),
        "-f", str(HELM_DIR / "environments" / env / f"{service}.yaml"),
        *extra,
    ]
    for key, value in (sets or {}).items():
        if value is None:  # helm deletes a key that is set to null
            cmd += ["--set", f"{key}=null"]
        elif isinstance(value, bool):  # real booleans and numbers must reach the chart as such, or the schema (rightly) rejects them
            cmd += ["--set", f"{key}={'true' if value else 'false'}"]
        elif isinstance(value, int):
            cmd += ["--set", f"{key}={value}"]
        else:
            cmd += ["--set-string", f"{key}={value}"]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise HelmError(result.stderr.strip())
    return [d for d in yaml.safe_load_all(result.stdout) if d]


def of_kind(docs, kind):
    return [d for d in docs if d["kind"] == kind]


def one(docs, kind, name=None):
    found = [d for d in of_kind(docs, kind) if name is None or d["metadata"]["name"] == name]
    assert len(found) == 1, f"expected one {kind} {name or ''}, found {len(found)}"
    return found[0]


def pod_specs(docs):
    """(label, pod spec) for every pod template the chart creates."""
    for d in docs:
        if d["kind"] == "Deployment":
            yield d["metadata"]["name"], d["spec"]["template"]["spec"]
        elif d["kind"] == "Job":
            yield d["metadata"]["name"], d["spec"]["template"]["spec"]
        elif d["kind"] == "CronJob":
            yield d["metadata"]["name"], d["spec"]["jobTemplate"]["spec"]["template"]["spec"]


ALL = [(s, e) for e in ENVS for s in SERVICES]


# ---- every pod is locked down -------------------------------------------------------------------------------------------------
@pytest.mark.parametrize(("service", "env"), ALL)
def test_every_pod_follows_the_restricted_security_profile(service, env):
    for name, spec in pod_specs(render(service, env)):
        sc = spec["securityContext"]
        assert sc["runAsNonRoot"] is True and sc["runAsUser"] == 10001, name
        assert sc["seccompProfile"]["type"] == "RuntimeDefault", name
        assert spec["automountServiceAccountToken"] is False, f"{name}: pods must not get a Kubernetes API token"
        assert spec.get("hostNetwork") is not True and spec.get("hostPID") is not True, name
        for c in spec["containers"]:
            csc = c["securityContext"]
            assert csc["allowPrivilegeEscalation"] is False, name
            assert csc["readOnlyRootFilesystem"] is True, name
            assert csc["capabilities"]["drop"] == ["ALL"], name
            assert not csc.get("privileged"), name
            assert c["resources"]["requests"]["cpu"] and c["resources"]["requests"]["memory"], name
            assert "memory" in c["resources"]["limits"], f"{name}: a memory limit stops one leak taking the node down"


@pytest.mark.parametrize(("service", "env"), ALL)
def test_the_only_writable_place_is_an_in_memory_tmp(service, env):
    for name, spec in pod_specs(render(service, env)):
        assert [v["name"] for v in spec["volumes"]] == ["tmp"], name
        assert spec["volumes"][0]["emptyDir"]["medium"] == "Memory", name
        assert [m["mountPath"] for c in spec["containers"] for m in c["volumeMounts"]] == ["/tmp"], name


@pytest.mark.parametrize(("service", "env"), ALL)
def test_images_come_from_our_registry_with_a_commit_tag_never_latest(service, env):
    docs = render(service, env)
    for _, spec in pod_specs(docs):
        for c in spec["containers"]:
            assert re.fullmatch(rf"\d{{12}}\.dkr\.ecr\.ap-south-1\.amazonaws\.com/school/{service}:[0-9a-f]{{7,40}}", c["image"]), c["image"]
            assert not c["image"].endswith(":latest")


# ---- secrets never enter Kubernetes -----------------------------------------------------------------------------------------------
@pytest.mark.parametrize(("service", "env"), ALL)
def test_the_chart_creates_no_secret_objects_and_the_config_holds_no_secret_values(service, env):
    docs = render(service, env)
    assert of_kind(docs, "Secret") == []
    data = one(docs, "ConfigMap")["data"]
    for key, value in data.items():
        if re.search(r"PASSWORD|PRIVATE_KEY|SECRET|TOKEN", key):
            assert key.endswith("_ARN"), f"{key} looks like a secret value in a ConfigMap"
        assert "BEGIN" not in value and "password" not in value.lower(), key


@pytest.mark.parametrize("service", SERVICES)
def test_each_service_is_given_only_its_own_database_login(service):
    docs = render(service, "dev")
    data = one(docs, "ConfigMap")["data"]
    assert data["DB_SECRET_ARN"].endswith(f"/db/{service}_app-AbCdEf")
    # the schema-changing login is reachable only from the migration job, never from the API's configuration
    assert "migrator" not in json.dumps(data)
    job = one(docs, "Job")
    env = {e["name"]: e["value"] for e in job["spec"]["template"]["spec"]["containers"][0]["env"]}
    assert env["DB_SECRET_ARN"].endswith(f"/db/{service}_migrator-GhIjKl")
    assert job["spec"]["template"]["spec"]["serviceAccountName"] == "db-migrator"


def test_only_auth_can_see_the_signing_key_arn():
    for service in SERVICES:
        data = one(render(service), "ConfigMap")["data"]
        assert ("JWT_PRIVATE_KEY_SECRET_ARN" in data) == (service == "auth"), service
        assert ("JWT_PUBLIC_KEY_SECRET_ARN" in data) == (service != "auth"), service


def test_event_queue_and_topic_settings_follow_each_services_role():
    expected_queue = {"admission", "fee", "attendance", "notification"}
    for service in SERVICES:
        data = one(render(service), "ConfigMap")["data"]
        assert ("SQS_QUEUE_URL" in data) == (service in expected_queue), service
        assert ("SNS_TOPIC_ARN" in data) == (service == "notification"), service
        assert ("STUDENT_SERVICE_URL" in data) == (service in {"admission", "fee", "attendance"}), service
        assert data["AUTO_CREATE_TABLES"] == "false"


# ---- deploying without downtime ---------------------------------------------------------------------------------------------------
@pytest.mark.parametrize("service", SERVICES)
def test_probes_rolling_update_and_graceful_shutdown(service):
    dep = one(render(service), "Deployment", service)
    c = dep["spec"]["template"]["spec"]["containers"][0]
    assert c["livenessProbe"]["httpGet"]["path"] == "/health"
    assert c["readinessProbe"]["httpGet"]["path"] == "/ready"
    assert c["startupProbe"]["httpGet"]["path"] == "/health"
    ru = dep["spec"]["strategy"]["rollingUpdate"]
    assert ru["maxUnavailable"] == 0 and ru["maxSurge"] == 1, "never remove a pod before its replacement is ready"
    sleep = int(c["lifecycle"]["preStop"]["exec"]["command"][1])
    assert dep["spec"]["template"]["spec"]["terminationGracePeriodSeconds"] > sleep, "grace period must outlast the preStop sleep"


@pytest.mark.parametrize("service", SERVICES)
def test_replicas_are_spread_across_zones(service):
    spread = one(render(service), "Deployment", service)["spec"]["template"]["spec"]["topologySpreadConstraints"]
    assert "topology.kubernetes.io/zone" in [s["topologyKey"] for s in spread]


def test_replicas_autoscaling_and_disruption_budgets_per_environment():
    dev = render("fee", "dev")
    assert one(dev, "Deployment", "fee")["spec"]["replicas"] == 1 and of_kind(dev, "PodDisruptionBudget") == []
    stage = render("fee", "stage")
    assert one(stage, "Deployment", "fee")["spec"]["replicas"] == 2
    assert one(stage, "PodDisruptionBudget")["spec"]["minAvailable"] == 1
    prod = render("fee", "prod")
    assert "replicas" not in one(prod, "Deployment", "fee")["spec"], "with an autoscaler, the HPA owns the replica count"
    hpa = one(prod, "HorizontalPodAutoscaler")
    assert hpa["spec"]["minReplicas"] == 3 and hpa["spec"]["maxReplicas"] == 8
    assert hpa["spec"]["metrics"][0]["resource"]["target"]["averageUtilization"] == 70


def test_a_config_change_restarts_the_pods():
    a = one(render("fee"), "Deployment", "fee")["spec"]["template"]["metadata"]["annotations"]["checksum/config"]
    b = one(render("fee", sets={"config.LOG_LEVEL_EXTRA": "x"}), "Deployment", "fee")["spec"]["template"]["metadata"]["annotations"]["checksum/config"]
    assert a != b


# ---- the load balancer's routes ---------------------------------------------------------------------------------------------------
def all_routes(env="dev"):
    routes = []
    for service in SERVICES:
        ing = one(render(service, env), "Ingress")
        order = int(ing["metadata"]["annotations"]["alb.ingress.kubernetes.io/group.order"])
        for p in ing["spec"]["rules"][0]["http"]["paths"]:
            routes.append((order, service, p["path"], p["pathType"]))
    return routes


def test_every_service_shares_one_load_balancer():
    groups = {one(render(s), "Ingress")["metadata"]["annotations"]["alb.ingress.kubernetes.io/group.name"] for s in SERVICES}
    assert groups == {"school-dev"}


def test_the_whole_api_surface_is_routed_to_the_right_service():
    owners = {path: service for _, service, path, _ in all_routes()}
    expected = {
        "/api/v1/auth": "auth", "/api/v1/users": "auth", "/.well-known/jwks.json": "auth",
        "/api/v1/admissions": "admission",
        "/api/v1/students": "student", "/api/v1/classes": "student", "/api/v1/sections": "student",
        "/api/v1/subjects": "student", "/api/v1/teachers": "student",
        "/api/v1/fees": "fee", "/api/v1/fee-structures": "fee", "/api/v1/payments": "fee", "/api/v1/students/*/fees": "fee",
        "/api/v1/attendance": "attendance", "/api/v1/students/*/attendance": "attendance", "/api/v1/teachers/*/attendance": "attendance",
        "/api/v1/notifications": "notification",
    }
    assert owners == expected


def test_specific_paths_are_evaluated_before_the_general_student_paths():
    """/students/{id}/fees starts with /students, but belongs to Fee. The load balancer checks lower order numbers first."""
    routes = all_routes()
    student_order = next(o for o, s, p, _ in routes if s == "student")
    for order, service, path, _ in routes:
        if service in {"fee", "attendance"} and path.startswith(("/api/v1/students/", "/api/v1/teachers/")):
            assert order < student_order, f"{service} {path} would be shadowed by the Student service"


def test_no_path_is_claimed_by_two_services():
    paths = [p for _, _, p, _ in all_routes()]
    assert len(paths) == len(set(paths))


def test_wildcard_paths_use_the_implementation_specific_type():
    for _, _, path, kind in all_routes():
        if "*" in path:
            assert kind == "ImplementationSpecific", path
        elif path.endswith(".json"):
            assert kind == "Exact", path
        else:
            assert kind == "Prefix", path


def test_the_load_balancer_listens_on_https_only_when_a_certificate_exists():
    http = one(render("fee"), "Ingress")["metadata"]["annotations"]
    assert http["alb.ingress.kubernetes.io/listen-ports"] == '[{"HTTP":80}]' and "alb.ingress.kubernetes.io/certificate-arn" not in http
    https = one(render("fee", sets={"global.ingress.certificateArn": "arn:aws:acm:ap-south-1:111111111111:certificate/abc"}), "Ingress")["metadata"]["annotations"]
    assert https["alb.ingress.kubernetes.io/listen-ports"] == '[{"HTTPS":443}]'
    assert https["alb.ingress.kubernetes.io/certificate-arn"].startswith("arn:aws:acm:")
    assert "TLS13" in https["alb.ingress.kubernetes.io/ssl-policy"] or "TLS-1-2" in https["alb.ingress.kubernetes.io/ssl-policy"]


def test_the_load_balancer_uses_the_cloudfront_only_security_group():
    a = one(render("fee"), "Ingress")["metadata"]["annotations"]
    assert a["alb.ingress.kubernetes.io/security-groups"] == "sg-0a1b2c3d4e5f60718"
    assert a["alb.ingress.kubernetes.io/target-type"] == "ip"
    assert a["alb.ingress.kubernetes.io/healthcheck-path"] == "/ready"


# ---- network policies -------------------------------------------------------------------------------------------------------------
def egress_targets(np):
    return [(r.get("to", [{}])[0], r.get("ports", [])) for r in np["spec"]["egress"]]


@pytest.mark.parametrize("service", SERVICES)
def test_pods_can_still_reach_the_pod_identity_agent_dns_and_the_database(service):
    np = one(render(service), "NetworkPolicy")
    cidrs = [(t.get("ipBlock", {}).get("cidr"), [p["port"] for p in ports]) for t, ports in egress_targets(np)]
    assert ("169.254.170.23/32", [80]) in cidrs, "without this every AWS call fails with 'no credentials'"
    assert ("10.10.0.0/16", [5432]) in cidrs
    assert any(t.get("namespaceSelector") and [p["port"] for p in ports] == [53, 53] for t, ports in egress_targets(np))
    assert {"Ingress", "Egress"} == set(np["spec"]["policyTypes"])


def calls_of(service):
    """Names of the school services this one may open connections to."""
    return [
        t["podSelector"]["matchLabels"]["app.kubernetes.io/name"]
        for t, _ in egress_targets(one(render(service), "NetworkPolicy"))
        if "app.kubernetes.io/name" in t.get("podSelector", {}).get("matchLabels", {})
    ]


def test_only_the_intended_services_can_call_each_other():
    callers = {
        s: [
            r["from"][0]["podSelector"]["matchLabels"]["app.kubernetes.io/name"]
            for r in one(render(s), "NetworkPolicy")["spec"]["ingress"]
            if "podSelector" in r["from"][0]
        ]
        for s in SERVICES
    }
    assert sorted(callers["student"]) == ["admission", "attendance", "fee"]
    assert all(callers[s] == [] for s in SERVICES if s != "student")
    for s in ("admission", "fee", "attendance"):
        assert calls_of(s) == ["student"], s
    for s in ("auth", "student", "notification"):
        assert calls_of(s) == [], s


def test_network_policy_can_be_turned_off():
    assert of_kind(render("fee", sets={"networkPolicy.enabled": False}), "NetworkPolicy") == []
    assert len(of_kind(render("fee"), "NetworkPolicy")) == 1


# ---- worker, cron job, migration --------------------------------------------------------------------------------------------------
def test_only_notification_has_a_queue_worker_and_it_is_the_same_image():
    for service in SERVICES:
        docs = render(service)
        workers = [d for d in of_kind(docs, "Deployment") if d["metadata"]["name"].endswith("-worker")]
        assert len(workers) == (1 if service == "notification" else 0), service
    docs = render("notification")
    api, worker = one(docs, "Deployment", "notification"), one(docs, "Deployment", "notification-worker")
    api_c, worker_c = api["spec"]["template"]["spec"]["containers"][0], worker["spec"]["template"]["spec"]["containers"][0]
    assert api_c["image"] == worker_c["image"]
    assert worker_c["command"] == ["python", "-m", "app.worker"] and "ports" not in worker_c
    assert "exec" in worker_c["livenessProbe"], "no HTTP port: liveness is a heartbeat file"
    assert worker["spec"]["template"]["spec"]["serviceAccountName"] == "notification"


def test_only_fee_has_a_cron_job_and_overlapping_runs_are_forbidden():
    for service in SERVICES:
        crons = of_kind(render(service), "CronJob")
        assert len(crons) == (1 if service == "fee" else 0), service
    cron = one(render("fee"), "CronJob")
    assert cron["spec"]["concurrencyPolicy"] == "Forbid"
    assert cron["spec"]["schedule"] == "0 3 * * *" and cron["spec"]["timeZone"] == "Etc/UTC"
    assert cron["spec"]["jobTemplate"]["spec"]["template"]["spec"]["containers"][0]["command"] == ["python", "-m", "app.jobs.overdue_reminders"]


def test_the_migration_job_is_a_hook_that_blocks_the_deploy_until_it_succeeds():
    job = one(render("student"), "Job")
    ann = job["metadata"]["annotations"]
    assert ann["helm.sh/hook"] == "pre-install,pre-upgrade"
    assert job["spec"]["template"]["spec"]["restartPolicy"] == "Never"
    assert job["spec"]["template"]["spec"]["containers"][0]["command"] == ["alembic", "upgrade", "head"]
    assert job["spec"]["activeDeadlineSeconds"] == 600


def test_migrations_can_be_switched_off():
    assert of_kind(render("student", sets={"migrations.enabled": False}), "Job") == []


# ---- the chart agrees with the Terraform it depends on -------------------------------------------------------------------------------
def terraform_services():
    text = (ROOT / "terraform/environments/dev/locals.tf").read_text()
    return re.search(r"services\s*=\s*\[(.*?)\]", text, re.S).group(1).replace('"', "").replace(" ", "").replace("\n", "").strip(",").split(",")


def test_services_in_the_chart_are_exactly_the_services_terraform_created_roles_for():
    assert sorted(terraform_services()) == sorted(SERVICES)


@pytest.mark.parametrize("service", SERVICES)
def test_service_account_names_match_the_pod_identity_associations(service):
    """Terraform links IAM roles to (namespace, service account) pairs. A different name here means no AWS permissions."""
    docs = render(service, "dev")
    assert one(docs, "ServiceAccount")["metadata"]["name"] == service
    for _, spec in pod_specs([d for d in docs if d["kind"] in ("Deployment", "CronJob")]):
        assert spec["serviceAccountName"] == service


@pytest.mark.parametrize("env", ENVS)
def test_the_namespace_and_load_balancer_group_match_terraform(env):
    outputs = json.loads((HELM_DIR / "tests/fixtures" / f"terraform-outputs-{env}.json").read_text())
    namespace = outputs["kubernetes_namespace"]["value"]
    assert namespace == f"school-{env}"
    ing = one(render("fee", env), "Ingress")
    assert ing["metadata"]["annotations"]["alb.ingress.kubernetes.io/group.name"] == namespace


def test_the_migration_service_account_matches_terraforms_database_job_role():
    text = (ROOT / "terraform/environments/dev/access.tf").read_text()
    assert '"db-migrator"' in text
    assert one(render("fee"), "Job")["spec"]["template"]["spec"]["serviceAccountName"] == "db-migrator"


# ---- the schema and the guard rails reject mistakes -------------------------------------------------------------------------------------
@pytest.mark.parametrize(
    ("overrides", "fragment"),
    [
        ({"image.tag": "latest"}, "tag"),
        ({"image.tag": "v1.2.3"}, "tag"),
        ({"image.tag": ""}, "tag"),
        ({"global.imageRegistry": "docker.io"}, "imageRegistry"),
        ({"global.environment": "qa"}, "environment"),
        ({"replicaCount": 0}, "replicaCount"),
    ],
)
def test_bad_values_are_rejected_before_anything_is_rendered(overrides, fragment):
    with pytest.raises(HelmError, match=fragment):
        render("fee", sets=overrides)


def test_a_misspelt_key_is_an_error_not_silently_ignored():
    with pytest.raises(HelmError):
        render("fee", sets={"replicas": "5"})  # the key is replicaCount


def test_an_unknown_service_is_rejected():
    with pytest.raises(HelmError):
        render("fee", sets={"service.name": "billing"})


def test_ingress_without_a_load_balancer_group_is_refused():
    with pytest.raises(HelmError, match="groupName"):
        render("fee", sets={"global.ingress.groupName": ""})


def test_an_empty_database_login_arn_is_rejected_by_the_schema():
    with pytest.raises(HelmError, match="dbAppArns/fee"):
        render("fee", sets={"global.secrets.dbAppArns.fee": ""})


def test_a_missing_database_login_is_rejected_before_anything_is_rendered():
    # The schema stops it first; the template has its own `required` as a second line of defence.
    with pytest.raises(HelmError, match="dbAppArns/fee"):
        render("fee", sets={"global.secrets.dbAppArns.fee": None})


def test_latest_is_refused_even_by_the_template_guard():
    with pytest.raises(HelmError):
        render("fee", sets={"image.tag": "latest"})


def test_pinning_by_digest_overrides_the_tag():
    digest = "sha256:" + "a" * 64
    docs = render("fee", sets={"image.digest": digest})
    assert one(docs, "Deployment", "fee")["spec"]["template"]["spec"]["containers"][0]["image"].endswith(f"@{digest}")


# ---- GitOps contract ----------------------------------------------------------------------------------------------------------------------
@pytest.mark.parametrize("env", ENVS)
def test_ci_only_ever_needs_to_change_the_image_tag(env):
    """Per-service environment files hold the deploy knob (image.tag) plus sizing; nothing else may creep in."""
    for service in SERVICES:
        data = yaml.safe_load((HELM_DIR / "environments" / env / f"{service}.yaml").read_text())
        assert set(data) <= {"image", "replicaCount", "autoscaling"}, (env, service)
        assert set(data["image"]) == {"tag"}


# ================================================================================================================================
# The platform chart: things shared by the whole namespace
# ================================================================================================================================
PLATFORM = HELM_DIR / "school-platform"


def render_platform(env="dev", sets=None):
    cmd = [str(HELM), "template", "school-platform", str(PLATFORM), "-n", f"school-{env}",
           "-f", str(HELM_DIR / "environments" / env / "common.yaml"), "-f", str(HELM_DIR / "environments" / env / "platform.yaml")]
    for key, value in (sets or {}).items():
        cmd += ["--set-string", f"{key}={value}"]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise HelmError(result.stderr.strip())
    return [d for d in yaml.safe_load_all(result.stdout) if d]


@pytest.mark.parametrize("env", ENVS)
def test_the_platform_chart_creates_the_shared_pieces(env):
    docs = render_platform(env)
    assert sorted(d["kind"] for d in docs) == ["Job", "LimitRange", "NetworkPolicy", "NetworkPolicy", "ServiceAccount"]
    assert one(docs, "ServiceAccount")["metadata"]["name"] == "db-migrator"


def test_the_namespace_denies_all_traffic_by_default():
    deny = one(render_platform(), "NetworkPolicy", "default-deny")
    assert deny["spec"]["podSelector"] == {} and set(deny["spec"]["policyTypes"]) == {"Ingress", "Egress"}
    assert "ingress" not in deny["spec"] and "egress" not in deny["spec"], "no allow rules: that is what makes it deny-all"


def test_the_bootstrap_job_runs_after_its_service_account_exists_and_is_locked_down():
    job = one(render_platform(), "Job")
    assert job["metadata"]["annotations"]["helm.sh/hook"] == "post-install,post-upgrade", "pre-install would run before the ServiceAccount exists"
    spec = job["spec"]["template"]["spec"]
    assert spec["serviceAccountName"] == "db-migrator" and spec["automountServiceAccountToken"] is False
    c = spec["containers"][0]
    assert spec["securityContext"]["runAsNonRoot"] and c["securityContext"]["readOnlyRootFilesystem"] and c["securityContext"]["capabilities"]["drop"] == ["ALL"]
    assert re.fullmatch(r"\d{12}\.dkr\.ecr\.ap-south-1\.amazonaws\.com/school/db-tools:[0-9a-f]{7,40}", c["image"])


def test_the_bootstrap_job_is_given_arns_not_secrets():
    c = one(render_platform(), "Job")["spec"]["template"]["spec"]["containers"][0]
    env = {e["name"]: e["value"] for e in c["env"]}
    assert env["MASTER_SECRET_ARN"].startswith("arn:aws:secretsmanager:")
    apps, migrators = json.loads(env["DB_APP_SECRET_ARNS"]), json.loads(env["DB_MIGRATOR_SECRET_ARNS"])
    assert sorted(apps) == sorted(migrators) == sorted(SERVICES)
    assert all(a.startswith("arn:aws:secretsmanager:") for a in [*apps.values(), *migrators.values()])
    assert not any("PASSWORD" in e["name"] for e in c["env"])


def test_the_bootstrap_job_can_reach_exactly_what_it_needs():
    np = one(render_platform(), "NetworkPolicy", "db-bootstrap")
    targets = {(r["to"][0].get("ipBlock", {}).get("cidr"), tuple(p["port"] for p in r["ports"])) for r in np["spec"]["egress"]}
    assert ("169.254.170.23/32", (80,)) in targets and ("10.10.0.0/16", (5432, 443)) in targets


@pytest.mark.parametrize(("key", "value"), [("dbTools.image.tag", "latest"), ("dbTools.image.tag", "v1"), ("global.imageRegistry", "docker.io")])
def test_the_platform_chart_rejects_bad_values(key, value):
    with pytest.raises(HelmError):
        render_platform(sets={key: value})


def test_the_platform_chart_requires_the_administrator_secret():
    with pytest.raises(HelmError):
        render_platform(sets={"global.secrets.rdsMasterArn": ""})


# ================================================================================================================================
# The generator that turns `terraform output` into Helm values
# ================================================================================================================================
import importlib.util  # noqa: E402

_spec = importlib.util.spec_from_file_location("render_env_values", ROOT / "scripts/helm/render-env-values.py")
gen = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(gen)


def fixture(env):
    return json.loads((HELM_DIR / "tests/fixtures" / f"terraform-outputs-{env}.json").read_text())


@pytest.mark.parametrize("env", ENVS)
def test_the_committed_values_are_exactly_what_the_generator_produces(env, tmp_path):
    """So nobody can hand-edit a generated file and have the edit silently survive."""
    out = tmp_path / "common.yaml"
    assert gen.main([env, str(HELM_DIR / "tests/fixtures" / f"terraform-outputs-{env}.json"), "--out", str(out)]) == 0
    assert out.read_text() == (HELM_DIR / "environments" / env / "common.yaml").read_text()


def test_the_generated_file_has_the_right_shape():
    values = gen.build_values("dev", gen.load_outputs(fixture("dev")))
    g = values["global"]
    assert sorted(g["secrets"]["dbAppArns"]) == sorted(SERVICES) and g["ingress"]["groupName"] == "school-dev"
    assert g["imageRegistry"].startswith("111111111111.dkr.ecr")  # stage and prod pull from the registry owner's account


def test_a_certificate_arn_is_passed_through_and_validated(tmp_path):
    out = tmp_path / "c.yaml"
    arn = "arn:aws:acm:ap-south-1:111111111111:certificate/abc"
    assert gen.main(["dev", str(HELM_DIR / "tests/fixtures/terraform-outputs-dev.json"), "--certificate-arn", arn, "--out", str(out)]) == 0
    assert f'certificateArn: "{arn}"' in out.read_text()
    assert gen.main(["dev", str(HELM_DIR / "tests/fixtures/terraform-outputs-dev.json"), "--certificate-arn", "nope", "--out", str(out)]) == 2


def test_the_generator_refuses_outputs_from_the_wrong_environment(tmp_path, capsys):
    assert gen.main(["prod", str(HELM_DIR / "tests/fixtures/terraform-outputs-dev.json"), "--out", str(tmp_path / "x.yaml")]) == 2
    assert "not 'prod'" in capsys.readouterr().err


def test_the_generator_explains_missing_outputs(tmp_path, capsys):
    broken = fixture("dev")
    del broken["events_queue_url"]
    path = tmp_path / "o.json"
    path.write_text(json.dumps(broken))
    assert gen.main(["dev", str(path), "--out", str(tmp_path / "x.yaml")]) == 2
    assert "events_queue_url" in capsys.readouterr().err and not (tmp_path / "x.yaml").exists()


def test_the_generator_refuses_a_missing_service_login(tmp_path, capsys):
    broken = fixture("dev")
    del broken["db_secret_arns"]["value"]["fee_migrator"]
    path = tmp_path / "o.json"
    path.write_text(json.dumps(broken))
    assert gen.main(["dev", str(path), "--out", str(tmp_path / "x.yaml")]) == 2
    assert "migrator" in capsys.readouterr().err


def test_generated_values_pass_the_chart_schema_for_every_service():
    for env in ENVS:
        for service in SERVICES:
            render(service, env)  # would raise HelmError if the generated file broke the strict schema


def test_the_generated_file_contains_no_secret_material():
    text = (HELM_DIR / "environments/dev/common.yaml").read_text()
    assert "BEGIN" not in text and "password" not in text.lower()
