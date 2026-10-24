mock_provider "aws" {
  mock_resource "aws_sns_topic" {
    defaults = {
      arn = "arn:aws:sns:ap-south-1:123456789012:school-test-notifications"
    }
  }
  mock_data "aws_caller_identity" {
    defaults = {
      account_id = "123456789012"
    }
  }
  mock_data "aws_iam_policy_document" {
    defaults = {
      json = "{\"Version\":\"2012-10-17\",\"Statement\":[]}"
    }
  }
}

variables {
  name = "school-test-notifications"
}

run "a_topic_with_no_subscribers_by_default" {
  command = plan

  assert {
    condition     = aws_sns_topic.this.name == "school-test-notifications" && length(aws_sns_topic_subscription.this) == 0
    error_message = "A new topic has no subscribers."
  }
  assert {
    condition     = aws_sns_topic.this.kms_master_key_id == null
    error_message = "Not encrypted unless a key is given (the alerts topic must stay readable by CloudWatch)."
  }
}

run "the_notifications_topic_can_be_encrypted" {
  command = plan
  variables {
    kms_master_key_id = "alias/aws/sns"
  }

  assert {
    condition     = aws_sns_topic.this.kms_master_key_id == "alias/aws/sns"
    error_message = "The key should be applied."
  }
}

run "subscriptions_are_keyed_by_the_callers_names" {
  command = plan
  variables {
    subscriptions = {
      ops-email = { protocol = "email", endpoint = "ops@school.example" }
      delivery = {
        protocol      = "lambda"
        endpoint      = "arn:aws:lambda:ap-south-1:123456789012:function:deliver"
        filter_policy = "{\"channel\":[\"EMAIL\",\"SMS\"]}"
      }
    }
  }

  assert {
    condition     = toset(keys(aws_sns_topic_subscription.this)) == toset(["ops-email", "delivery"])
    error_message = "One subscription per entry, keyed by the chosen name."
  }
  assert {
    condition     = aws_sns_topic_subscription.this["delivery"].filter_policy_scope == "MessageAttributes"
    error_message = "A filter is matched against message attributes (the Notification Service sets channel and event_type as attributes)."
  }
}

run "a_topic_policy_is_always_attached" {
  command = apply
  variables {
    allow_cloudwatch_alarms = true
  }

  assert {
    condition     = aws_sns_topic_policy.this.arn != null
    error_message = "The topic policy (TLS only, owner access, optional alarms) must exist."
  }
}
