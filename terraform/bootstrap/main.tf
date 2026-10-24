# BOOTSTRAP: creates the S3 bucket that holds Terraform's own state for this environment's AWS account.
#
# It is a chicken-and-egg problem: the state bucket cannot be created by a configuration that already stores its
# state in that bucket. So this one small configuration uses LOCAL state (a terraform.tfstate file in this folder,
# git-ignored). Run it once per AWS account, then every other configuration keeps its state in the bucket.

provider "aws" {
  region              = var.aws_region
  allowed_account_ids = var.allowed_account_ids

  default_tags {
    tags = {
      Project     = var.project
      Environment = var.environment
      ManagedBy   = "terraform"
      Owner       = var.owner
      Component   = "terraform-state"
    }
  }
}

data "aws_caller_identity" "current" {}

locals {
  # Bucket names are global across all of AWS, so the account id makes the name unique AND tells you whose it is.
  bucket_name = "${var.project}-tfstate-${data.aws_caller_identity.current.account_id}-${var.aws_region}"
}

resource "aws_s3_bucket" "state" {
  bucket = local.bucket_name

  # Losing this bucket means losing track of every resource Terraform built. Terraform will refuse to destroy
  # it; to delete it on purpose, remove this block first (a deliberate two-step).
  lifecycle {
    prevent_destroy = true
  }
}

# Every `apply` writes a new version. If a state file is corrupted or wrongly edited, you restore an older one.
resource "aws_s3_bucket_versioning" "state" {
  bucket = aws_s3_bucket.state.id

  versioning_configuration {
    status = "Enabled"
  }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "state" {
  bucket = aws_s3_bucket.state.id

  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256" # State can contain secrets (for example generated passwords), so it is always encrypted
    }
    bucket_key_enabled = true
  }
}

# State must never be public. All four switches on, so no later policy or ACL can open it up by mistake.
resource "aws_s3_bucket_public_access_block" "state" {
  bucket = aws_s3_bucket.state.id

  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_ownership_controls" "state" {
  bucket = aws_s3_bucket.state.id

  rule {
    object_ownership = "BucketOwnerEnforced" # switches ACLs off: only policies decide access
  }
}

resource "aws_s3_bucket_lifecycle_configuration" "state" {
  bucket = aws_s3_bucket.state.id

  # The lock file is created and deleted around every run; old versions pile up. Keep a useful window, not forever.
  rule {
    id     = "expire-old-state-versions"
    status = "Enabled"

    filter {}

    noncurrent_version_expiration {
      noncurrent_days = var.noncurrent_version_retention_days
    }

    abort_incomplete_multipart_upload {
      days_after_initiation = 7
    }
  }

  depends_on = [aws_s3_bucket_versioning.state] # lifecycle rules for versions need versioning switched on first
}

data "aws_iam_policy_document" "state" {
  statement {
    sid       = "DenyInsecureTransport"
    effect    = "Deny"
    actions   = ["s3:*"]
    resources = [aws_s3_bucket.state.arn, "${aws_s3_bucket.state.arn}/*"]

    principals {
      type        = "*"
      identifiers = ["*"]
    }

    condition {
      test     = "Bool"
      variable = "aws:SecureTransport"
      values   = ["false"]
    }
  }

  statement {
    sid       = "DenyOldTls"
    effect    = "Deny"
    actions   = ["s3:*"]
    resources = [aws_s3_bucket.state.arn, "${aws_s3_bucket.state.arn}/*"]

    principals {
      type        = "*"
      identifiers = ["*"]
    }

    condition {
      test     = "NumericLessThan"
      variable = "s3:TlsVersion"
      values   = ["1.2"]
    }
  }
}

resource "aws_s3_bucket_policy" "state" {
  bucket = aws_s3_bucket.state.id
  policy = data.aws_iam_policy_document.state.json

  depends_on = [aws_s3_bucket_public_access_block.state] # avoids a race between the policy and the public-access block
}
