mock_provider "aws" {
  mock_data "aws_iam_policy_document" {
    defaults = {
      json = "{\"Version\":\"2012-10-17\",\"Statement\":[]}"
    }
  }
}

variables {
  name = "school-test-events"
}

run "a_queue_and_its_dead_letter_queue_are_created" {
  command = apply

  assert {
    condition     = aws_sqs_queue.main.name == "school-test-events" && aws_sqs_queue.dlq.name == "school-test-events-dlq"
    error_message = "The dead-letter queue is named <queue>-dlq."
  }
  assert {
    condition     = jsondecode(aws_sqs_queue.main.redrive_policy).maxReceiveCount == 3 && jsondecode(aws_sqs_queue.main.redrive_policy).deadLetterTargetArn == aws_sqs_queue.dlq.arn
    error_message = "After 3 failed receives a message must move to THE dead-letter queue."
  }
}

run "only_the_main_queue_may_use_the_dead_letter_queue" {
  command = apply

  assert {
    condition     = jsondecode(aws_sqs_queue_redrive_allow_policy.dlq.redrive_allow_policy).redrivePermission == "byQueue" && contains(jsondecode(aws_sqs_queue_redrive_allow_policy.dlq.redrive_allow_policy).sourceQueueArns, aws_sqs_queue.main.arn)
    error_message = "The dead-letter queue must accept messages from the main queue only."
  }
}

run "failed_messages_are_kept_longer_than_normal_ones" {
  command = plan

  assert {
    condition     = aws_sqs_queue.dlq.message_retention_seconds > aws_sqs_queue.main.message_retention_seconds
    error_message = "Dead letters need a human, so they must outlive normal messages."
  }
  assert {
    condition     = aws_sqs_queue.main.message_retention_seconds == 4 * 86400 && aws_sqs_queue.dlq.message_retention_seconds == 14 * 86400
    error_message = "Defaults: 4 days and 14 days."
  }
}

run "long_polling_and_encryption_are_on_by_default" {
  command = plan

  assert {
    condition     = aws_sqs_queue.main.receive_wait_time_seconds == 20
    error_message = "Long polling (20s) should be the default."
  }
  assert {
    condition     = aws_sqs_queue.main.sqs_managed_sse_enabled == true && aws_sqs_queue.dlq.sqs_managed_sse_enabled == true
    error_message = "Both queues must be encrypted at rest."
  }
}

run "a_kms_key_replaces_the_managed_encryption" {
  command = plan
  variables {
    kms_master_key_id = "arn:aws:kms:ap-south-1:123456789012:key/11111111-2222-3333-4444-555555555555"
  }

  assert {
    condition     = aws_sqs_queue.main.kms_master_key_id != null && aws_sqs_queue.dlq.kms_master_key_id != null
    error_message = "Both queues must use the given KMS key."
  }
}

run "tls_only_policies_are_attached_to_both_queues" {
  command = plan

  assert {
    condition     = length(aws_sqs_queue_policy.tls_only) == 2
    error_message = "Both queues need the deny-insecure-transport policy."
  }
}

run "visibility_timeout_is_configurable" {
  command = plan
  variables {
    visibility_timeout_seconds = 120
    max_receive_count          = 5
  }

  assert {
    condition     = aws_sqs_queue.main.visibility_timeout_seconds == 120
    error_message = "Visibility timeout should follow the input."
  }
}

run "rejects_an_absurd_receive_count" {
  command = plan
  variables {
    max_receive_count = 0
  }
  expect_failures = [var.max_receive_count]
}
