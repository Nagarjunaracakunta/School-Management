from dataclasses import dataclass, field
from enum import StrEnum

import jwt

from app.config.settings import Settings
from app.utils.errors import UnauthorizedError


class Role(StrEnum):
    ADMIN = "admin"
    TEACHER = "teacher"
    PARENT = "parent"


@dataclass(frozen=True)
class CurrentUser:
    id: str
    role: Role
    name: str
    email: str = ""
    token: str = field(default="", repr=False, compare=False)  # forwarded to other services


def decode_token(token: str, settings: Settings) -> CurrentUser:
    """Verify signature, expiry, issuer and audience, then build the user from the claims."""
    try:
        claims = jwt.decode(
            token,
            settings.jwt_public_key,
            algorithms=[settings.jwt_algorithm],  # pinned: never trust the token's own "alg"
            issuer=settings.jwt_issuer,
            audience=settings.jwt_audience,
            options={"require": ["exp", "sub", "iss", "aud"]},
        )
        return CurrentUser(
            id=claims["sub"],
            role=Role(claims["role"]),
            name=claims.get("name", ""),
            email=claims.get("email", "").lower(),
            token=token,
        )
    except (jwt.PyJWTError, KeyError, ValueError) as exc:
        # Same message for every failure: do not tell an attacker what was wrong.
        raise UnauthorizedError("Invalid or expired token") from exc
