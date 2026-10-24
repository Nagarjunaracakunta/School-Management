import datetime as dt
import uuid
from enum import StrEnum
from typing import Annotated

from pydantic import BaseModel, EmailStr, Field, StringConstraints, field_validator, model_validator

from app.services.passwords import validate_password


class UserRole(StrEnum):
    ADMIN = "admin"
    TEACHER = "teacher"
    PARENT = "parent"


class LoginRequest(BaseModel):
    email: EmailStr
    # Deliberately NOT run through the password policy: old accounts must still be able to log in,
    # and a policy error here would tell an attacker what the rules are.
    password: Annotated[str, StringConstraints(min_length=1, max_length=256)]


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int  # seconds


class UserCreate(BaseModel):
    email: EmailStr
    full_name: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=120)]
    role: UserRole
    password: str

    @model_validator(mode="after")
    def _check_password(self) -> "UserCreate":
        validate_password(self.password, str(self.email))
        return self


class UserUpdate(BaseModel):
    full_name: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=120)] | None = None
    role: UserRole | None = None
    is_active: bool | None = None

    @model_validator(mode="after")
    def _something_to_change(self) -> "UserUpdate":
        if self.full_name is None and self.role is None and self.is_active is None:
            raise ValueError("provide full_name, role and/or is_active")
        return self


class PasswordReset(BaseModel):
    new_password: str


class PasswordChange(BaseModel):
    current_password: Annotated[str, StringConstraints(min_length=1, max_length=256)]
    new_password: str = Field(min_length=1)

    @field_validator("new_password")
    @classmethod
    def _policy(cls, v: str) -> str:
        return validate_password(v)


class UserOut(BaseModel):
    id: uuid.UUID
    email: str
    full_name: str
    role: UserRole
    is_active: bool
    last_login_at: dt.datetime | None
    created_at: dt.datetime
