mock_provider "aws" {
  mock_data "aws_iam_policy_document" {
    defaults = {
      json = "{\"Version\":\"2012-10-17\",\"Statement\":[]}"
    }
  }
}

variables {
  repositories = ["auth", "fee", "student"]
}

run "one_repository_per_image_with_the_project_prefix" {
  command = plan

  assert {
    condition     = toset([for r in aws_ecr_repository.this : r.name]) == toset(["school/auth", "school/fee", "school/student"])
    error_message = "Repositories should be named <prefix>/<short name>."
  }
}

run "tags_are_immutable_and_images_are_scanned_by_default" {
  command = plan

  assert {
    condition     = alltrue([for r in aws_ecr_repository.this : r.image_tag_mutability == "IMMUTABLE"])
    error_message = "Tags must be immutable: a tag must always mean the same image."
  }
  assert {
    condition     = alltrue([for r in aws_ecr_repository.this : one(r.image_scanning_configuration).scan_on_push])
    error_message = "Scan on push must be on."
  }
  assert {
    condition     = alltrue([for r in aws_ecr_repository.this : one(r.encryption_configuration).encryption_type == "AES256"])
    error_message = "Without a KMS key, images use the AES256 default."
  }
}

run "a_kms_key_switches_encryption_to_kms" {
  command = plan
  variables {
    kms_key_arn = "arn:aws:kms:ap-south-1:123456789012:key/11111111-2222-3333-4444-555555555555"
  }

  assert {
    condition     = alltrue([for r in aws_ecr_repository.this : one(r.encryption_configuration).encryption_type == "KMS"])
    error_message = "Providing a key should select KMS encryption."
  }
}

run "every_repository_has_a_lifecycle_policy_so_storage_cannot_grow_forever" {
  command = plan
  variables {
    untagged_expire_days = 3
    keep_last_images     = 10
  }

  assert {
    condition     = length(aws_ecr_lifecycle_policy.this) == 3
    error_message = "One lifecycle policy per repository."
  }
  assert {
    condition     = jsondecode(aws_ecr_lifecycle_policy.this["fee"].policy).rules[0].selection.countNumber == 3 && jsondecode(aws_ecr_lifecycle_policy.this["fee"].policy).rules[1].selection.countNumber == 10
    error_message = "The policy should use the configured retention numbers."
  }
  assert {
    condition     = jsondecode(aws_ecr_lifecycle_policy.this["fee"].policy).rules[0].rulePriority < jsondecode(aws_ecr_lifecycle_policy.this["fee"].policy).rules[1].rulePriority
    error_message = "The 'any tag' rule must have the lowest priority (highest number), or ECR rejects the policy."
  }
}

run "no_cross_account_policy_by_default" {
  command = plan

  assert {
    condition     = length(aws_ecr_repository_policy.pull) == 0
    error_message = "Pull access for other accounts must be opt-in."
  }
}

run "other_accounts_can_pull_when_listed" {
  command = plan
  variables {
    pull_account_ids = ["222222222222", "333333333333"]
  }

  assert {
    condition     = length(aws_ecr_repository_policy.pull) == 3
    error_message = "Each repository needs the cross-account pull policy."
  }
}

run "rejects_bad_input" {
  command = plan
  variables {
    repositories = ["Has Spaces"]
  }
  expect_failures = [var.repositories]
}

run "rejects_a_malformed_account_id" {
  command = plan
  variables {
    pull_account_ids = ["abc"]
  }
  expect_failures = [var.pull_account_ids]
}

run "rejects_unknown_mutability" {
  command = plan
  variables {
    image_tag_mutability = "SOMETIMES"
  }
  expect_failures = [var.image_tag_mutability]
}
