# Offline test: the AWS provider is replaced by a mock, so no account or credentials are needed.
mock_provider "aws" {
  mock_data "aws_caller_identity" {
    defaults = {
      account_id = "123456789012"
    }
  }
  mock_data "aws_iam_policy_document" {
    defaults = {
      json = "{\"mock\":true}"
    }
  }
}

variables {
  environment         = "dev"
  allowed_account_ids = ["123456789012"]
}

run "bucket_is_named_after_project_account_and_region" {
  command = plan

  assert {
    condition     = aws_s3_bucket.state.bucket == "school-tfstate-123456789012-ap-south-1"
    error_message = "State bucket name should be <project>-tfstate-<account>-<region>."
  }
}

run "state_is_protected" {
  command = plan

  assert {
    condition     = aws_s3_bucket_versioning.state.versioning_configuration[0].status == "Enabled"
    error_message = "Versioning must be enabled so a bad state file can be rolled back."
  }
  assert {
    condition = alltrue([
      aws_s3_bucket_public_access_block.state.block_public_acls,
      aws_s3_bucket_public_access_block.state.block_public_policy,
      aws_s3_bucket_public_access_block.state.ignore_public_acls,
      aws_s3_bucket_public_access_block.state.restrict_public_buckets,
    ])
    error_message = "All four public-access blocks must be on."
  }
  assert {
    condition     = one(one(aws_s3_bucket_server_side_encryption_configuration.state.rule).apply_server_side_encryption_by_default).sse_algorithm == "AES256"
    error_message = "State must be encrypted at rest."
  }
}

run "wrong_environment_is_rejected" {
  command = plan
  variables {
    environment = "production"
  }
  expect_failures = [var.environment]
}

run "malformed_account_id_is_rejected" {
  command = plan
  variables {
    allowed_account_ids = ["not-an-account"]
  }
  expect_failures = [var.allowed_account_ids]
}
