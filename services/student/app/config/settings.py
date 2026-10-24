from datetime import date
from functools import lru_cache
from pathlib import Path

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy.engine import URL

from app.config import aws_secrets


def default_academic_year(today: date | None = None) -> str:
    """School years run April-March: 2026-10-24 -> '2026-27', 2027-02-01 -> '2026-27'."""
    today = today or date.today()
    start = today.year if today.month >= 4 else today.year - 1
    return f"{start}-{(start + 1) % 100:02d}"


class Settings(BaseSettings):
    """All configuration comes from environment variables (12-factor). No defaults for secrets."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    service_name: str = "student-service"
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

    current_academic_year: str = ""

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
        self.current_academic_year = self.current_academic_year or default_academic_year()
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
