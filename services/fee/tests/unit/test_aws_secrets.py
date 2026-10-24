import json

import boto3
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from moto import mock_aws

from app.config import aws_secrets
from app.config.settings import Settings

REGION = "ap-south-1"
EXTRA: dict = {}
TRICKY_PASSWORD = "p@ss:w/ord#1?&=%"  # characters that break a naive connection string


@pytest.fixture(autouse=True)
def aws(monkeypatch):
    for key, value in {
        "AWS_ACCESS_KEY_ID": "testing",
        "AWS_SECRET_ACCESS_KEY": "testing",
        "AWS_DEFAULT_REGION": REGION,
    }.items():
        monkeypatch.setenv(key, value)
    monkeypatch.delenv("AWS_ENDPOINT_URL", raising=False)
    with mock_aws():
        yield boto3.client("secretsmanager", region_name=REGION)


def put(client, name, value) -> str:
    return client.create_secret(Name=name, SecretString=value)["ARN"]


def db_login(client, name="school/dev/db/svc_app", **override) -> str:
    login = {
        "username": "svc_svc",
        "password": TRICKY_PASSWORD,
        "host": "db.example.internal",
        "port": 5432,
        "dbname": "school",
    }
    return put(client, name, json.dumps({**login, **override}))


def public_key_pem() -> str:
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    return (
        key.public_key()
        .public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo)
        .decode()
    )


def test_a_database_login_is_read_from_secrets_manager(aws):
    login = aws_secrets.read_db_login(db_login(aws))
    assert (login["username"], login["host"], login["dbname"]) == ("svc_svc", "db.example.internal", "school")


def test_the_url_escapes_special_characters_in_the_password(aws):
    url = aws_secrets.db_url_from_secret(db_login(aws))
    assert url.password == TRICKY_PASSWORD and url.host == "db.example.internal" and url.port == 5432
    assert TRICKY_PASSWORD not in url.render_as_string(hide_password=False)  # it is percent-encoded, not pasted in raw


@pytest.mark.parametrize(
    "bad",
    [
        "not json",
        json.dumps({"username": "only-this"}),
        json.dumps({"username": "u", "password": "", "host": "h", "port": 1, "dbname": "d"}),
    ],
)
def test_a_malformed_login_is_refused_without_echoing_it(aws, bad):
    arn = put(aws, "school/dev/db/bad", bad)
    with pytest.raises(aws_secrets.SecretLoadError) as err:
        aws_secrets.read_db_login(arn)
    assert "only-this" not in str(err.value) and "not json" not in str(err.value)


def test_a_missing_secret_names_the_problem_but_not_any_secret_value(aws):
    arn = f"arn:aws:secretsmanager:{REGION}:123456789012:secret:school/dev/db/ghost-AbCdEf"
    with pytest.raises(aws_secrets.SecretLoadError, match="could not read secret"):
        aws_secrets.get_secret_text(arn)


def test_only_secrets_manager_arns_are_accepted():
    with pytest.raises(aws_secrets.SecretLoadError, match="not a Secrets Manager ARN"):
        aws_secrets.get_secret_text("arn:aws:s3:::my-bucket")


def test_settings_are_filled_in_from_the_secrets_the_chart_points_at(aws):
    settings = Settings(
        _env_file=None,
        db_secret_arn=db_login(aws),
        jwt_public_key_secret_arn=put(aws, "school/dev/jwt/public-key", public_key_pem()),
        **EXTRA,
    )
    assert settings.db_user == "svc_svc" and settings.db_host == "db.example.internal" and settings.db_port == 5432
    assert settings.sqlalchemy_url.password == TRICKY_PASSWORD
    assert "BEGIN PUBLIC KEY" in settings.jwt_public_key


def test_an_explicit_database_url_wins_and_no_secret_is_read(aws):
    ghost = f"arn:aws:secretsmanager:{REGION}:123456789012:secret:school/dev/db/ghost-AbCdEf"
    settings = Settings(
        _env_file=None, database_url="sqlite://", db_secret_arn=ghost, jwt_public_key=public_key_pem(), **EXTRA
    )
    assert settings.database_url == "sqlite://"  # the unreadable secret was never touched


def test_a_service_that_cannot_read_its_secret_fails_to_start_with_a_clear_message(aws):
    ghost = f"arn:aws:secretsmanager:{REGION}:123456789012:secret:school/dev/db/ghost-AbCdEf"
    with pytest.raises(ValueError, match="could not read secret"):
        Settings(_env_file=None, db_secret_arn=ghost, jwt_public_key=public_key_pem(), **EXTRA)
