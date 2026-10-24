mock_provider "aws" {
  mock_data "aws_caller_identity" {
    defaults = {
      account_id = "123456789012"
    }
  }
}

variables {
  name_prefix         = "school-test"
  github_repository   = "acme/school-management"
  ecr_repository_arns = ["arn:aws:ecr:ap-south-1:123456789012:repository/school/fee"]
}

run "only_the_named_environment_of_the_named_repository_can_assume_the_role" {
  command = apply

  assert {
    condition     = jsondecode(aws_iam_role.ecr_push[0].assume_role_policy).Statement[0].Condition.StringEquals["token.actions.githubusercontent.com:sub"] == "repo:acme/school-management:environment:registry-push"
    error_message = "The trust must be pinned to repo + environment, not a wildcard."
  }
  assert {
    condition     = jsondecode(aws_iam_role.ecr_push[0].assume_role_policy).Statement[0].Condition.StringEquals["token.actions.githubusercontent.com:aud"] == "sts.amazonaws.com"
    error_message = "The audience must be checked."
  }
  assert {
    condition     = !strcontains(aws_iam_role.ecr_push[0].assume_role_policy, "*")
    error_message = "No wildcard anywhere in the trust policy."
  }
}

run "the_role_can_push_to_listed_repositories_and_nothing_else" {
  command = apply

  assert {
    condition     = jsondecode(aws_iam_role_policy.ecr_push[0].policy).Statement[1].Resource == ["arn:aws:ecr:ap-south-1:123456789012:repository/school/fee"]
    error_message = "Pushing is limited to the listed repositories."
  }
  assert {
    condition     = !contains(jsondecode(aws_iam_role_policy.ecr_push[0].policy).Statement[1].Action, "ecr:DeleteRepository") && !contains(jsondecode(aws_iam_role_policy.ecr_push[0].policy).Statement[1].Action, "ecr:BatchDeleteImage")
    error_message = "The pipeline must not be able to delete images or repositories."
  }
}

run "the_website_role_can_write_one_bucket_and_invalidate_one_distribution_and_nothing_else" {
  command = apply
  variables {
    frontend_github_environment = "frontend-dev"
    create_frontend_deploy_role = true
    frontend_bucket_arn         = "arn:aws:s3:::school-dev-frontend-123456789012"
    frontend_distribution_arn   = "arn:aws:cloudfront::123456789012:distribution/E123ABC"
  }

  assert {
    condition     = jsondecode(aws_iam_role.frontend_deploy[0].assume_role_policy).Statement[0].Condition.StringEquals["token.actions.githubusercontent.com:sub"] == "repo:acme/school-management:environment:frontend-dev"
    error_message = "The website role trusts one GitHub Environment of one repository."
  }
  assert {
    condition     = toset(flatten([for st in jsondecode(aws_iam_role_policy.frontend_deploy[0].policy).Statement : st.Action])) == toset(["s3:ListBucket", "s3:PutObject", "s3:DeleteObject", "cloudfront:CreateInvalidation"])
    error_message = "Exactly: list, put, delete, invalidate."
  }
  assert {
    condition     = alltrue([for st in jsondecode(aws_iam_role_policy.frontend_deploy[0].policy).Statement : !strcontains(jsonencode(st.Resource), "*") || st.Resource == "arn:aws:s3:::school-dev-frontend-123456789012/*"])
    error_message = "Only the object path of the one bucket may end in a wildcard."
  }
}

run "an_environment_without_a_registry_gets_no_push_role" {
  command = apply
  variables {
    ecr_repository_arns = []
  }

  assert {
    condition     = length(aws_iam_role.ecr_push) == 0 && length(aws_iam_role.frontend_deploy) == 0
    error_message = "Roles exist only when their resources were given."
  }
}

run "the_provider_is_created_once_and_can_be_reused" {
  command = apply

  assert {
    condition     = length(aws_iam_openid_connect_provider.github) == 1
    error_message = "By default the provider is created."
  }
}

run "an_existing_provider_is_not_created_again" {
  command = apply
  variables {
    create_provider = false
  }

  assert {
    condition     = length(aws_iam_openid_connect_provider.github) == 0
    error_message = "With create_provider = false nothing is created."
  }
}

run "a_malformed_repository_name_is_refused" {
  command = plan
  variables {
    github_repository = "not-a-repo"
  }
  expect_failures = [var.github_repository]
}
