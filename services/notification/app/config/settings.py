from functools import lru_cache
from pathlib import Path

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy.engine import URL

from app.config import aws_secrets


class Settings(BaseSettings):
    """All configuration comes from environment variables (12-factor). No defaults for secrets."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    service_name: str = "notification-service"
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
    auto_create_tables: bool = False  # local/test only; Phase 9 adds real migrations

    jwt_public_key: str | None = None
    jwt_public_key_secret_arn: str | None = None  # Secrets Manager ARN of the verification key
    jwt_public_key_file: str | None = None
    jwt_algorithm: str = "RS256"
    jwt_issuer: str = "school-auth"
    jwt_audience: str = "school-api"

    # Messaging. Credentials come from the pod's IAM role (IRSA), never from keys in config.
    sqs_queue_url: str = ""  # required by the worker, not by the API
    sns_topic_arn: str = ""  # empty = log instead of publish (local only)
    aws_region: str = "ap-south-1"

    # Delivery
    max_delivery_attempts: int = Field(default=3, ge=1, le=10)
    poll_wait_seconds: int = Field(default=20, ge=0, le=20)  # SQS long polling
    poll_batch_size: int = Field(default=10, ge=1, le=10)
    retry_base_delay_seconds: int = Field(default=30, ge=1)
    retry_max_delay_seconds: int = Field(default=900, ge=1)
    heartbeat_file: str = "/tmp/notification-worker-heartbeat"  # a Kubernetes exec probe checks its age

    @model_validator(mode="after")
    def _validate(self) -> "Settings":
        # In Kubernetes the chart provides ARNs; the secrets themselves are read here with the pod's own IAM role.
        if self.db_secret_arn and not self.database_url:
            login = aws_secrets.read_db_login(self.db_secret_arn)
            self.db_host, self.db_port, self.db_name = login["host"], int(login["port"]), login["dbname"]
            self.db_user, self.db_password = login["username"], login["password"]
        if self.jwt_public_key_secret_arn and not self.jwt_public_key:
            self.jwt_public_key = aws_secrets.get_secret_text(self.jwt_public_key_secret_arn)
        if not self.database_url and not (self.db_host and self.db_user and self.db_password):
            raise ValueError("Set DATABASE_URL, or DB_HOST + DB_USER + DB_PASSWORD")
        if self.jwt_public_key_file and not self.jwt_public_key:
            self.jwt_public_key = Path(self.jwt_public_key_file).read_text()
        if not self.jwt_public_key:
            raise ValueError("Set JWT_PUBLIC_KEY or JWT_PUBLIC_KEY_FILE")
        self.jwt_public_key = self.jwt_public_key.replace("\\n", "\n")
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
