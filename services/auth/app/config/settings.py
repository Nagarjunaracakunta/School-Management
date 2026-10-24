from functools import lru_cache
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy.engine import URL

from app.config import aws_secrets


class Settings(BaseSettings):
    """All configuration comes from environment variables (12-factor). No defaults for secrets."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    service_name: str = "auth-service"
    environment: str = "local"
    log_level: str = "INFO"

    database_url: str | None = None
    db_host: str | None = None
    db_port: int = 5432
    db_name: str = "school"
    db_user: str | None = None
    db_password: str | None = None  # injected from Secrets Manager
    db_secret_arn: str | None = None  # Secrets Manager ARN of this service's database login (read at startup)
    db_pool_size: int = 5
    auto_create_tables: bool = False  # local/test only; real environments use Alembic migrations

    # Token signing. The PRIVATE key never leaves this service; the other services get the public half.
    jwt_private_key: str | None = None
    jwt_private_key_secret_arn: str | None = None  # Secrets Manager ARN of the signing key
    jwt_private_key_file: str | None = None
    jwt_public_key: str | None = None  # derived from the private key, used to verify tokens on /users, /me
    jwt_algorithm: str = "RS256"
    jwt_issuer: str = "school-auth"
    jwt_audience: str = "school-api"
    access_token_ttl_minutes: int = Field(default=30, ge=1, le=1440)

    # Brute-force protection
    max_failed_logins: int = Field(default=5, ge=1)
    lockout_minutes: int = Field(default=15, ge=1)

    # Argon2id cost. The defaults follow current OWASP guidance; tests lower them to stay fast.
    argon2_time_cost: int = Field(default=3, ge=1)
    argon2_memory_kib: int = Field(default=65536, ge=8)
    argon2_parallelism: int = Field(default=4, ge=1)

    @model_validator(mode="after")
    def _validate(self) -> "Settings":
        # In Kubernetes the chart provides ARNs; the secrets themselves are read here with the pod's own IAM role.
        if self.db_secret_arn and not self.database_url:
            login = aws_secrets.read_db_login(self.db_secret_arn)
            self.db_host, self.db_port, self.db_name = login["host"], int(login["port"]), login["dbname"]
            self.db_user, self.db_password = login["username"], login["password"]
        if self.jwt_private_key_secret_arn and not self.jwt_private_key:
            self.jwt_private_key = aws_secrets.get_secret_text(self.jwt_private_key_secret_arn)
        if not self.database_url and not (self.db_host and self.db_user and self.db_password):
            raise ValueError("Set DATABASE_URL, or DB_HOST + DB_USER + DB_PASSWORD")
        if self.jwt_private_key_file and not self.jwt_private_key:
            self.jwt_private_key = Path(self.jwt_private_key_file).read_text()
        if not self.jwt_private_key:
            raise ValueError("Set JWT_PRIVATE_KEY or JWT_PRIVATE_KEY_FILE")
        self.jwt_private_key = self.jwt_private_key.replace("\\n", "\n")
        try:
            key = serialization.load_pem_private_key(self.jwt_private_key.encode(), password=None)
        except ValueError as exc:
            raise ValueError("JWT private key is not a valid unencrypted PEM key") from exc
        self.jwt_public_key = (
            key.public_key()
            .public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo)
            .decode()
        )
        return self

    @property
    def sqlalchemy_url(self) -> str | URL:
        if self.database_url:
            return self.database_url
        return URL.create(
            "postgresql+psycopg",
            username=self.db_user,
            password=self.db_password,
            host=self.db_host,
            port=self.db_port,
            database=self.db_name,
        )


@lru_cache
def get_settings() -> Settings:
    return Settings()
