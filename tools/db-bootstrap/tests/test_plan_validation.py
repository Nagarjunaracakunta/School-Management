"""Checks run BEFORE the database is touched. No PostgreSQL needed."""

import json

import pytest

import bootstrap
from bootstrap import BootstrapError, build_plan

pytestmark = pytest.mark.usefixtures("fake_aws")


def test_a_correct_set_of_secrets_gives_a_plan(world):
    plan = build_plan(world.environ())
    assert sorted(plan.apps) == ["admission", "fee", "student"]
    assert plan.apps["fee"].username == "fee_svc" and plan.migrators["fee"].username == "fee_migrator"
    assert (plan.host, plan.port, plan.dbname) == ("db.example.internal", 5432, "school")


@pytest.mark.parametrize("hijack", ["school_admin", "postgres", "rdsadmin", "fee_migrator"])
def test_a_secret_naming_someone_elses_role_is_refused(world, hijack):
    """The safety rule: a mistaken or tampered secret must never be able to reset the administrator's password."""
    world.app_arns["fee"] = world.login_secret("fee", "app", username=hijack)
    with pytest.raises(BootstrapError, match="must be exactly 'fee_svc'"):
        build_plan(world.environ())


def test_the_migrator_secret_cannot_name_the_app_role_either(world):
    world.migrator_arns["student"] = world.login_secret("student", "migrator", username="student_svc")
    with pytest.raises(BootstrapError, match="must be exactly 'student_migrator'"):
        build_plan(world.environ())


def test_a_weak_password_is_refused(world):
    world.app_arns["fee"] = world.login_secret("fee", "app", pw="short")
    with pytest.raises(BootstrapError, match="too short"):
        build_plan(world.environ())


def test_secrets_pointing_at_different_databases_are_refused(world):
    world.app_arns["fee"] = world.login_secret("fee", "app", host="another-host.example.internal")
    with pytest.raises(BootstrapError, match="different databases"):
        build_plan(world.environ())


def test_missing_fields_are_refused(world):
    arn = world.put("school/test/db/incomplete", {"username": "fee_svc", "password": "x" * 20})
    world.app_arns["fee"] = arn
    with pytest.raises(BootstrapError, match="lacks: host, port, dbname"):
        build_plan(world.environ())


def test_the_two_lists_must_cover_the_same_services(world):
    del world.migrator_arns["fee"]
    with pytest.raises(BootstrapError, match="same services"):
        build_plan(world.environ())


def test_an_unknown_service_is_refused(world):
    world.app_arns["billing"] = world.migrator_arns["billing"] = world.app_arns["fee"]
    with pytest.raises(BootstrapError, match="unknown service.*billing"):
        build_plan(world.environ())


@pytest.mark.parametrize("name", ["MASTER_SECRET_ARN"])
def test_a_missing_administrator_secret_is_refused(world, name):
    env = world.environ()
    del env[name]
    with pytest.raises(BootstrapError, match="MASTER_SECRET_ARN"):
        build_plan(env)


def test_bad_configuration_is_reported_clearly(world):
    for key, value, message in (
        ("DB_APP_SECRET_ARNS", "not json", "not valid JSON"),
        ("DB_APP_SECRET_ARNS", "[]", "JSON object"),
        ("DB_MIGRATOR_SECRET_ARNS", json.dumps({"fee": "arn:aws:s3:::bucket"}), "same services|Secrets Manager"),
    ):
        env = {**world.environ(), key: value}
        with pytest.raises(BootstrapError, match=message):
            build_plan(env)


def test_an_unreadable_secret_names_the_problem_but_not_a_value(world):
    ghost = "arn:aws:secretsmanager:ap-south-1:123456789012:secret:school/test/db/ghost-AbCdEf"
    env = {**world.environ(), "MASTER_SECRET_ARN": ghost}
    with pytest.raises(BootstrapError, match="could not read secret"):
        build_plan(env)


def test_identifiers_are_validated_before_they_reach_sql():
    for bad in ("Fee", "fee; drop table x", "1abc", "a" * 60, ""):
        with pytest.raises(BootstrapError, match="unsafe identifier"):
            bootstrap._ident(bad)
