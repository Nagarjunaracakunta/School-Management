mock_provider "aws" {}

variables {
  name_prefix = "school-test"
  roles = {
    fee = {
      description = "Fee service"
      statements = [
        { sid = "SendEvents", actions = ["sqs:SendMessage"], resources = ["arn:aws:sqs:ap-south-1:123456789012:school-test-events"] },
        { sid = "ReadOwnSecret", actions = ["secretsmanager:GetSecretValue"], resources = ["arn:aws:secretsmanager:ap-south-1:123456789012:secret:school/test/db/fee_app-AbCdEf"] },
      ]
    }
    notification = {
      description = "Notification service"
      statements = [
        { sid = "Consume", actions = ["sqs:ReceiveMessage", "sqs:DeleteMessage"], resources = ["arn:aws:sqs:ap-south-1:123456789012:school-test-events"] },
      ]
    }
  }
}

run "one_role_per_service_named_after_the_prefix" {
  command = plan

  assert {
    condition     = toset([for r in aws_iam_role.this : r.name]) == toset(["school-test-fee", "school-test-notification"])
    error_message = "Roles are named <prefix>-<service>."
  }
  assert {
    condition     = length(aws_iam_role_policy.this) == 2
    error_message = "Each role gets its own inline policy."
  }
}

run "the_policy_grants_exactly_what_was_listed_and_nothing_else" {
  command = plan

  assert {
    condition     = length(jsondecode(aws_iam_role_policy.this["fee"].policy).Statement) == 2
    error_message = "Two statements in, two statements out."
  }
  assert {
    condition     = jsondecode(aws_iam_role_policy.this["fee"].policy).Statement[0].Action == ["sqs:SendMessage"] && jsondecode(aws_iam_role_policy.this["fee"].policy).Statement[0].Effect == "Allow"
    error_message = "The fee role may send messages, and only that."
  }
  assert {
    condition     = !contains(flatten([for st in jsondecode(aws_iam_role_policy.this["fee"].policy).Statement : st.Action]), "sqs:ReceiveMessage")
    error_message = "A producer must not be able to consume."
  }
}

run "only_the_eks_pod_identity_service_can_assume_a_role" {
  command = plan

  assert {
    condition     = jsondecode(aws_iam_role.this["fee"].assume_role_policy).Statement[0].Principal.Service == "pods.eks.amazonaws.com"
    error_message = "Only EKS Pod Identity may hand these credentials to pods."
  }
  assert {
    condition     = contains(jsondecode(aws_iam_role.this["fee"].assume_role_policy).Statement[0].Action, "sts:TagSession")
    error_message = "Pod Identity needs sts:TagSession as well as sts:AssumeRole."
  }
}

run "each_role_is_tagged_with_its_service" {
  command = plan

  assert {
    condition     = aws_iam_role.this["fee"].tags["Service"] == "fee"
    error_message = "The Service tag helps find who owns a role."
  }
}

run "a_wildcard_action_is_refused" {
  command = plan
  variables {
    roles = {
      bad = {
        description = "x"
        statements  = [{ sid = "Everything", actions = ["sqs:*"], resources = ["arn:aws:sqs:ap-south-1:123456789012:q"] }]
      }
    }
  }
  expect_failures = [var.roles]
}

run "the_all_actions_wildcard_is_refused" {
  command = plan
  variables {
    roles = {
      bad = {
        description = "x"
        statements  = [{ sid = "Everything", actions = ["*"], resources = ["arn:aws:sqs:ap-south-1:123456789012:q"] }]
      }
    }
  }
  expect_failures = [var.roles]
}

run "a_wildcard_resource_is_refused" {
  command = plan
  variables {
    roles = {
      bad = {
        description = "x"
        statements  = [{ sid = "AnyQueue", actions = ["sqs:SendMessage"], resources = ["*"] }]
      }
    }
  }
  expect_failures = [var.roles]
}

run "a_partial_wildcard_resource_is_refused_too" {
  command = plan
  variables {
    roles = {
      bad = {
        description = "x"
        statements  = [{ sid = "AnyBucketObject", actions = ["s3:GetObject"], resources = ["arn:aws:s3:::my-bucket/*"] }]
      }
    }
  }
  expect_failures = [var.roles]
}

run "a_role_without_permissions_is_refused" {
  command = plan
  variables {
    roles = {
      empty = { description = "x", statements = [] }
    }
  }
  expect_failures = [var.roles]
}

run "a_statement_id_with_spaces_is_refused" {
  command = plan
  variables {
    roles = {
      bad = {
        description = "x"
        statements  = [{ sid = "has spaces", actions = ["sqs:SendMessage"], resources = ["arn:aws:sqs:ap-south-1:123456789012:q"] }]
      }
    }
  }
  expect_failures = [var.roles]
}
