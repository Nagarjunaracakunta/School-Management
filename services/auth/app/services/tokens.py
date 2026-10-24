import datetime as dt
import hashlib
import json
import uuid
from typing import Any

import jwt
from cryptography.hazmat.primitives import serialization

from app.config.settings import Settings
from app.models.user import User


class TokenIssuer:
    """Signs access tokens (RS256). Other services verify them with the PUBLIC key only: they can check a
    token but can never forge one."""

    def __init__(self, settings: Settings) -> None:
        self._private_key = settings.jwt_private_key
        self._algorithm = settings.jwt_algorithm
        self._issuer = settings.jwt_issuer
        self._audience = settings.jwt_audience
        self.ttl_seconds = settings.access_token_ttl_minutes * 60
        public_der = serialization.load_pem_public_key(settings.jwt_public_key.encode()).public_bytes(
            serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo
        )
        # Key id: a fingerprint of the public key. Putting it in every token's header lets services pick the
        # right key from the JWKS list during a key rotation, when two keys are valid at once.
        self.key_id = hashlib.sha256(public_der).hexdigest()[:16]
        self._public_pem = settings.jwt_public_key

    def issue(self, user: User, now: dt.datetime | None = None) -> str:
        now = now or dt.datetime.now(dt.UTC)
        claims: dict[str, Any] = {
            "sub": str(user.id),
            "role": user.role,
            "name": user.full_name,
            "email": user.email,
            "iss": self._issuer,
            "aud": self._audience,
            "iat": int(now.timestamp()),
            "exp": int(now.timestamp()) + self.ttl_seconds,
            "jti": str(uuid.uuid4()),  # unique id per token, for audit trails and future revocation lists
        }
        return jwt.encode(claims, self._private_key, algorithm=self._algorithm, headers={"kid": self.key_id})

    def jwks(self) -> dict:
        """The public key in the standard JSON Web Key Set format (RFC 7517)."""
        jwk = json.loads(
            jwt.algorithms.RSAAlgorithm.to_jwk(serialization.load_pem_public_key(self._public_pem.encode()))
        )
        jwk.update({"kid": self.key_id, "use": "sig", "alg": self._algorithm})
        return {"keys": [jwk]}
