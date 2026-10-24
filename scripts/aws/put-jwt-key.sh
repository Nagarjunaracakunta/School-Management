#!/usr/bin/env bash
# Generates the token signing key pair and stores it in AWS Secrets Manager. Run ONCE per environment, after
# `terraform apply` has created the (empty) secrets.
#
#   AWS_PROFILE=school-dev scripts/aws/put-jwt-key.sh dev              # create and store a new key pair
#   AWS_PROFILE=school-dev scripts/aws/put-jwt-key.sh dev --rotate     # replace the key (all issued tokens stop working)
#   scripts/aws/put-jwt-key.sh dev --dry-run                           # generate and check a pair; talks to nobody
#
# Why not Terraform? Anything Terraform creates passes through its state file. A signing key should never be there.
# The key exists only in a private temporary folder for a few seconds, and is never printed.
set -euo pipefail

ENVIRONMENT="${1:?usage: put-jwt-key.sh <dev|stage|prod> [--rotate|--dry-run]}"
MODE="${2:-create}"
case "$ENVIRONMENT" in dev|stage|prod) ;; *) echo "environment must be dev, stage or prod" >&2; exit 2 ;; esac
case "$MODE" in create|--rotate|--dry-run) ;; *) echo "unknown option $MODE" >&2; exit 2 ;; esac

PROJECT="${PROJECT:-school}"
PRIVATE_ID="$PROJECT/$ENVIRONMENT/jwt/private-key"
PUBLIC_ID="$PROJECT/$ENVIRONMENT/jwt/public-key"

WORK="$(mktemp -d)"; chmod 700 "$WORK"
trap 'rm -rf "$WORK"' EXIT    # whatever happens, the temporary key files are deleted

openssl genpkey -algorithm RSA -pkeyopt rsa_keygen_bits:3072 -out "$WORK/private.pem" 2>/dev/null
openssl pkey -in "$WORK/private.pem" -pubout -out "$WORK/public.pem"

# Prove the pair belongs together BEFORE storing anything: sign something with one half, verify with the other.
echo "token-signing self test" > "$WORK/msg"
openssl dgst -sha256 -sign "$WORK/private.pem" -out "$WORK/sig" "$WORK/msg"
openssl dgst -sha256 -verify "$WORK/public.pem" -signature "$WORK/sig" "$WORK/msg" >/dev/null
FINGERPRINT="$(openssl pkey -pubin -in "$WORK/public.pem" -outform DER | openssl dgst -sha256 | awk '{print substr($NF,1,16)}')"
echo "generated a 3072-bit RSA key pair; self test passed; public key fingerprint $FINGERPRINT"

if [[ "$MODE" == "--dry-run" ]]; then echo "dry run: nothing was stored"; exit 0; fi

# Refuse to overwrite a key that is already there (that would log everybody out) unless asked to.
if [[ "$MODE" != "--rotate" ]] && aws secretsmanager get-secret-value --secret-id "$PRIVATE_ID" --query SecretString --output text >/dev/null 2>&1; then
  echo "A signing key already exists for $ENVIRONMENT. Use --rotate to replace it (everyone will have to log in again)." >&2
  exit 1
fi

aws secretsmanager put-secret-value --secret-id "$PRIVATE_ID" --secret-string "file://$WORK/private.pem" >/dev/null
aws secretsmanager put-secret-value --secret-id "$PUBLIC_ID"  --secret-string "file://$WORK/public.pem"  >/dev/null
echo "stored $PRIVATE_ID and $PUBLIC_ID (public key fingerprint $FINGERPRINT)"
echo "restart the Auth service and the other services so they pick up the new key"
