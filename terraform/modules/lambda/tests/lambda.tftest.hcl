mock_provider "aws" {
  mock_resource "aws_iam_role" {
    defaults = {
      arn = "arn:aws:iam::123456789012:role/school-test-fn"
    }
  }
  mock_resource "aws_lambda_function" {
    defaults = {
      arn = "arn:aws:lambda:ap-south-1:123456789012:function:school-test-fn"
    }
  }
  mock_resource "aws_cloudwatch_log_group" {
    defaults = {
      arn = "arn:aws:logs:ap-south-1:123456789012:log-group:/aws/lambda/school-test-fn"
    }
  }
}
mock_provider "archive" {
  mock_data "archive_file" {
    defaults = {
      output_path         = "/tmp/school-test-fn.zip"
      output_base64sha256 = "bW9ja2VkLWhhc2g="
    }
  }
}

variables {
  name       = "school-test-fn"
  source_dir = "."
}

run "a_plain_function_runs_on_arm_with_a_short_timeout" {
  command = plan

  assert {
    condition     = aws_lambda_function.this.runtime == "python3.12" && one(aws_lambda_function.this.architectures) == "arm64"
    error_message = "Python 3.12 on arm64 (Graviton) by default."
  }
  assert {
    condition     = aws_lambda_function.this.timeout == 30 && aws_lambda_function.this.memory_size == 128
    error_message = "Small and quick by default."
  }
  assert {
    condition     = aws_lambda_function.this.source_code_hash == "bW9ja2VkLWhhc2g="
    error_message = "The function must redeploy exactly when the zipped code changes."
  }
}

run "logs_have_a_retention_period" {
  command = plan
  variables {
    log_retention_days = 14
  }

  assert {
    condition     = aws_cloudwatch_log_group.this.name == "/aws/lambda/school-test-fn" && aws_cloudwatch_log_group.this.retention_in_days == 14
    error_message = "We own the log group so we can set retention."
  }
}

run "no_trigger_unless_a_topic_is_given" {
  command = plan

  assert {
    condition     = length(aws_sns_topic_subscription.this) == 0 && length(aws_lambda_permission.sns) == 0
    error_message = "No SNS subscription or permission by default."
  }
}

run "an_sns_topic_triggers_the_function_and_only_that_topic_may_invoke_it" {
  command = plan
  variables {
    sns_trigger = {
      topic_arn     = "arn:aws:sns:ap-south-1:123456789012:school-test-notifications"
      filter_policy = "{\"channel\":[\"EMAIL\"]}"
    }
  }

  assert {
    condition     = aws_lambda_permission.sns[0].source_arn == var.sns_trigger.topic_arn && aws_lambda_permission.sns[0].principal == "sns.amazonaws.com"
    error_message = "The invoke permission must be limited to the one topic."
  }
  assert {
    condition     = aws_sns_topic_subscription.this[0].protocol == "lambda" && aws_sns_topic_subscription.this[0].filter_policy_scope == "MessageAttributes"
    error_message = "A lambda subscription whose filter matches message attributes."
  }
}

run "failed_invocations_go_to_a_queue_instead_of_being_lost" {
  command = plan
  variables {
    failure_queue = { arn = "arn:aws:sqs:ap-south-1:123456789012:school-test-failures" }
  }

  assert {
    condition     = length(aws_lambda_function.this.dead_letter_config) == 1 && aws_lambda_function.this.dead_letter_config[0].target_arn == var.failure_queue.arn
    error_message = "Failed invocations must be parked in the failure queue."
  }
}

run "no_failure_queue_means_no_dead_letter_config" {
  command = plan

  assert {
    condition     = length(aws_lambda_function.this.dead_letter_config) == 0
    error_message = "No dead-letter config unless a queue is given."
  }
}

run "environment_variables_are_passed_through" {
  command = plan
  variables {
    environment = { FROM_ADDRESS = "no-reply@school.example" }
  }

  assert {
    condition     = one(aws_lambda_function.this.environment).variables["FROM_ADDRESS"] == "no-reply@school.example"
    error_message = "Environment variables should reach the function."
  }
}

run "retries_and_concurrency_are_configurable" {
  command = plan
  variables {
    retry_attempts       = 1
    reserved_concurrency = 5
  }

  assert {
    condition     = aws_lambda_function_event_invoke_config.this.maximum_retry_attempts == 1 && aws_lambda_function.this.reserved_concurrent_executions == 5
    error_message = "Retry count and concurrency cap follow the inputs."
  }
}

run "wildcard_permissions_are_refused" {
  command = plan
  variables {
    statements = [{ sid = "Anything", actions = ["ses:*"], resources = ["arn:aws:ses:ap-south-1:123456789012:identity/x"] }]
  }
  expect_failures = [var.statements]
}

run "a_function_can_write_only_its_own_logs_by_default" {
  command = apply

  assert {
    condition     = length(jsondecode(aws_iam_role_policy.this.policy).Statement) == 1 && jsondecode(aws_iam_role_policy.this.policy).Statement[0].Sid == "WriteOwnLogs"
    error_message = "With no extra permissions the role can do one thing: write its logs."
  }
  assert {
    condition     = jsondecode(aws_iam_role_policy.this.policy).Statement[0].Resource == ["${aws_cloudwatch_log_group.this.arn}:*"]
    error_message = "Logs go to the function's own log group only."
  }
}

run "sms_permission_comes_with_a_deny_on_every_topic" {
  command = apply
  variables {
    allow_sms_publish = true
  }

  assert {
    condition     = contains([for s in jsondecode(aws_iam_role_policy.this.policy).Statement : s.Sid], "SendTextMessages") && contains([for s in jsondecode(aws_iam_role_policy.this.policy).Statement : s.Sid], "NeverPublishToTopics")
    error_message = "The wildcard Allow must always be paired with the topic Deny."
  }
  assert {
    condition     = one([for s in jsondecode(aws_iam_role_policy.this.policy).Statement : s if s.Sid == "NeverPublishToTopics"]).Effect == "Deny"
    error_message = "The topic rule must be a Deny (a Deny always beats an Allow)."
  }
}

run "no_sms_permission_unless_asked_for" {
  command = apply

  assert {
    condition     = !contains([for s in jsondecode(aws_iam_role_policy.this.policy).Statement : s.Sid], "SendTextMessages")
    error_message = "Texting is opt-in."
  }
}

run "the_failure_queue_gets_write_access_only_when_configured" {
  command = apply
  variables {
    failure_queue = { arn = "arn:aws:sqs:ap-south-1:123456789012:school-test-failures" }
  }

  assert {
    condition     = one([for s in jsondecode(aws_iam_role_policy.this.policy).Statement : s if s.Sid == "WriteFailedInvocationsToQueue"]).Resource == ["arn:aws:sqs:ap-south-1:123456789012:school-test-failures"]
    error_message = "Write access to exactly that queue."
  }
}

# REGRESSION GUARD for a real bug found when the environment was wired together. The topic and queue there are created in
# the same run as the function, so their ARNs are UNKNOWN when Terraform plans. A module that decides "create the trigger?"
# from the ARN itself (var.x == null) fails with "Invalid count argument". The fixture creates the topic and queue itself, so the
# ARNs really are unknown, exactly like the environment.
run "triggers_work_when_the_topic_and_queue_are_created_in_the_same_run" {
  command = plan
  module {
    source = "./tests/fixtures/unknown_arns"
  }
  variables {
    source_dir = "."
  }

  assert {
    condition     = output.trigger_count == 1
    error_message = "The SNS trigger must be created even though the topic ARN is not known until apply."
  }
}
