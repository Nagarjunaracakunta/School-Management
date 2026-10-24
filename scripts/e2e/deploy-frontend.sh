#!/usr/bin/env bash
# Publishes a built React bundle: copy to the private bucket, then make CloudFront forget its old copies.
#
#   scripts/e2e/deploy-frontend.sh <bundle-folder> <bucket> <distribution-id> [--dry-run]
#
# Why two uploads: files in assets/ have a fingerprint in their name (index-BLTs-S3Q.js), so a changed file gets a NEW name and
# the old one may be cached for a year. index.html has a fixed name and points at the current fingerprints, so it must never
# be cached, or visitors keep seeing the previous version after a deploy.
set -euo pipefail

DIR="${1:?usage: deploy-frontend.sh <bundle-folder> <bucket> <distribution-id> [--dry-run]}"
BUCKET="${2:?bucket}"
DIST="${3:?distribution id}"
DRY="${4:-}"

[[ -f "$DIR/index.html" ]] || { echo "no index.html in $DIR: is this the output of 'npm run build'?" >&2; exit 1; }
[[ "$BUCKET" =~ ^[a-z0-9][a-z0-9.-]{2,62}$ ]] || { echo "does not look like a bucket name: $BUCKET" >&2; exit 1; }

run() { if [[ "$DRY" == "--dry-run" ]]; then echo "+ $*"; else "$@"; fi; }

run aws s3 sync "$DIR/" "s3://$BUCKET/" --delete --exclude index.html --exclude "*.map" --cache-control "public,max-age=31536000,immutable"
run aws s3 cp "$DIR/index.html" "s3://$BUCKET/index.html" --cache-control "no-cache" --content-type "text/html; charset=utf-8"
run aws cloudfront create-invalidation --distribution-id "$DIST" --paths "/index.html" "/"
[[ "$DRY" == "--dry-run" ]] && echo "(dry run: nothing was changed)" || echo "published to s3://$BUCKET"
