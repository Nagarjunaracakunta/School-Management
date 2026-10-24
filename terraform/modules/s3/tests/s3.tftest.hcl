mock_provider "aws" {}

variables {
  name = "school-test-frontend"
}

run "a_private_versioned_encrypted_bucket" {
  command = plan

  assert {
    condition     = aws_s3_bucket.this.bucket == "school-test-frontend" && aws_s3_bucket.this.force_destroy == false
    error_message = "The bucket takes its name from the input and is not force-destroyable by default."
  }
  assert {
    condition     = aws_s3_bucket_versioning.this.versioning_configuration[0].status == "Enabled"
    error_message = "Versioning should be on by default."
  }
  assert {
    condition = alltrue([
      aws_s3_bucket_public_access_block.this.block_public_acls,
      aws_s3_bucket_public_access_block.this.block_public_policy,
      aws_s3_bucket_public_access_block.this.ignore_public_acls,
      aws_s3_bucket_public_access_block.this.restrict_public_buckets,
    ])
    error_message = "All four public-access blocks must be on."
  }
  assert {
    condition     = one(one(aws_s3_bucket_server_side_encryption_configuration.this.rule).apply_server_side_encryption_by_default).sse_algorithm == "AES256"
    error_message = "Encrypted at rest."
  }
}

run "a_kms_key_changes_the_algorithm" {
  command = plan
  variables {
    kms_key_arn = "arn:aws:kms:ap-south-1:123456789012:key/11111111-2222-3333-4444-555555555555"
  }

  assert {
    condition     = one(one(aws_s3_bucket_server_side_encryption_configuration.this.rule).apply_server_side_encryption_by_default).sse_algorithm == "aws:kms"
    error_message = "With a key, the algorithm must be aws:kms."
  }
}

run "dev_can_allow_force_destroy_and_turn_versioning_off" {
  command = plan
  variables {
    force_destroy = true
    versioning    = false
  }

  assert {
    condition     = aws_s3_bucket.this.force_destroy && aws_s3_bucket_versioning.this.versioning_configuration[0].status == "Suspended"
    error_message = "Both switches should be honoured."
  }
}

run "old_versions_expire" {
  command = plan
  variables {
    noncurrent_version_days = 10
  }

  assert {
    condition     = one(one(aws_s3_bucket_lifecycle_configuration.this.rule).noncurrent_version_expiration).noncurrent_days == 10
    error_message = "Old versions expire after the configured number of days."
  }
}
