#!/usr/bin/env bash
# Creates a LOCAL RSA signing key pair in .dev-keys/ (git-ignored) if there is none. Only the Auth service gets the
# private key; every other service gets the public key. In AWS the private key lives in Secrets Manager.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DIR="$ROOT/.dev-keys"
mkdir -p "$DIR"
if [[ ! -f "$DIR/jwt_private.pem" ]]; then
  openssl genpkey -algorithm RSA -pkeyopt rsa_keygen_bits:2048 -out "$DIR/jwt_private.pem" 2>/dev/null
  chmod 600 "$DIR/jwt_private.pem"
  openssl pkey -in "$DIR/jwt_private.pem" -pubout -out "$DIR/jwt_public.pem"
  # The mounted files are read by the non-root container user (uid 10001): the PUBLIC key may be world-readable.
  chmod 644 "$DIR/jwt_public.pem"
  echo "created $DIR/jwt_private.pem and jwt_public.pem" >&2
fi
