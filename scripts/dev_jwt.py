#!/usr/bin/env python3
"""LOCAL DEV ONLY: mint a JWT so you can call services before the Auth Service exists (Phase 10).

Usage:  python scripts/dev_jwt.py [admin|teacher|parent] [user-id] [email]
Creates .dev-keys/ (git-ignored) on first run. The services verify tokens with the PUBLIC key;
the private key stays here. Never use this in a shared or real environment.
"""
import sys
import time
from pathlib import Path

import jwt
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

KEY_DIR = Path(__file__).resolve().parent.parent / ".dev-keys"
PRIVATE, PUBLIC = KEY_DIR / "jwt_private.pem", KEY_DIR / "jwt_public.pem"


def ensure_keys() -> None:
    if PRIVATE.exists():
        return
    KEY_DIR.mkdir(exist_ok=True)
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    PRIVATE.write_bytes(
        key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption())
    )
    PRIVATE.chmod(0o600)
    PUBLIC.write_bytes(
        key.public_key().public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo)
    )


if __name__ == "__main__":
    role = sys.argv[1] if len(sys.argv) > 1 else "admin"
    user_id = sys.argv[2] if len(sys.argv) > 2 else f"dev-{role}"
    email = sys.argv[3] if len(sys.argv) > 3 else f"{user_id}@example.com"
    ensure_keys()
    claims = {
        "sub": user_id, "role": role, "name": f"Dev {role.title()}", "email": email, "iss": "school-auth",
        "aud": "school-api", "exp": int(time.time()) + 3600,
    }
    print(jwt.encode(claims, PRIVATE.read_text(), algorithm="RS256"))
