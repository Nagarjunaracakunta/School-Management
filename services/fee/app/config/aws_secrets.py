"""Reads this service's secrets from AWS Secrets Manager at startup, using the pod's own IAM role (EKS Pod Identity).

The Helm chart gives the pod only the ARN of each secret: an address, not a secret. Reading the secrets here, instead
of copying them into Kubernetes Secrets, means nothing secret is stored in the cluster, each service can read only the
secrets its own IAM role allows, and rotating a secret needs only a pod restart.

On a laptop or in tests none of this runs: the ARN settings are simply not set.
"""

import json

from sqlalchemy.engine import URL

DB_LOGIN_KEYS = ("username", "password", "host", "port", "dbname")


class SecretLoadError(ValueError):
    """A secret could not be read or has an unexpected shape. The message never contains the secret itself."""


def _client(arn: str):
    if not arn.startswith("arn:aws:secretsmanager:"):
        raise SecretLoadError(f"not a Secrets Manager ARN: {arn!r}")
    import boto3  # imported here so a laptop without AWS settings never needs it

    return boto3.client("secretsmanager", region_name=arn.split(":")[3])  # the region is part of the ARN


def get_secret_text(arn: str) -> str:
    try:
        return _client(arn).get_secret_value(SecretId=arn)["SecretString"]
    except SecretLoadError:
        raise
    except Exception as exc:  # AccessDenied, not found, no network ... name the problem, not the details
        raise SecretLoadError(f"could not read secret {arn}: {type(exc).__name__}") from exc


def read_db_login(arn: str) -> dict:
    """The JSON login Terraform wrote: username, password, host, port, dbname."""
    try:
        login = json.loads(get_secret_text(arn))
    except json.JSONDecodeError as exc:
        raise SecretLoadError(f"secret {arn} is not valid JSON") from exc
    missing = [k for k in DB_LOGIN_KEYS if not login.get(k)]
    if missing:
        raise SecretLoadError(f"secret {arn} lacks: {', '.join(missing)}")
    return login


def db_url_from_secret(arn: str) -> URL:
    login = read_db_login(arn)
    return URL.create(  # URL.create escapes special characters in the password safely
        "postgresql+psycopg",
        username=login["username"],
        password=login["password"],
        host=login["host"],
        port=int(login["port"]),
        database=login["dbname"],
    )
