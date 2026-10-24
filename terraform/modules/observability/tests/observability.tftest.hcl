mock_provider "aws" {}

variables {
  name            = "school-test"
  alarm_topic_arn = "arn:aws:sns:ap-south-1:123456789012:school-test-alerts"
}

run "nothing_to_watch_means_no_alarms" {
  command = plan

  assert {
    condition     = length(aws_cloudwatch_metric_alarm.dlq_not_empty) + length(aws_cloudwatch_metric_alarm.queue_backlog_age) + length(aws_cloudwatch_metric_alarm.rds) + length(aws_cloudwatch_metric_alarm.lambda_errors) == 0
    error_message = "No inputs, no alarms."
  }
}

run "any_message_in_a_dead_letter_queue_raises_an_alarm" {
  command = plan
  variables {
    dead_letter_queue_names = ["school-test-events-dlq"]
  }

  assert {
    condition     = aws_cloudwatch_metric_alarm.dlq_not_empty["school-test-events-dlq"].threshold == 0 && aws_cloudwatch_metric_alarm.dlq_not_empty["school-test-events-dlq"].comparison_operator == "GreaterThanThreshold"
    error_message = "One message is enough."
  }
  assert {
    condition     = aws_cloudwatch_metric_alarm.dlq_not_empty["school-test-events-dlq"].treat_missing_data == "notBreaching"
    error_message = "An idle queue publishes no data; that is not an outage."
  }
}

run "alarms_notify_the_topic_on_trouble_and_on_recovery" {
  command = plan
  variables {
    dead_letter_queue_names = ["school-test-events-dlq"]
  }

  assert {
    condition     = contains(aws_cloudwatch_metric_alarm.dlq_not_empty["school-test-events-dlq"].alarm_actions, var.alarm_topic_arn) && contains(aws_cloudwatch_metric_alarm.dlq_not_empty["school-test-events-dlq"].ok_actions, var.alarm_topic_arn)
    error_message = "Tell people when it breaks AND when it is fixed."
  }
}

run "a_stuck_consumer_is_detected_by_the_age_of_the_oldest_message" {
  command = plan
  variables {
    queue_names           = ["school-test-events"]
    queue_max_age_seconds = 600
  }

  assert {
    condition     = aws_cloudwatch_metric_alarm.queue_backlog_age["school-test-events"].threshold == 600 && aws_cloudwatch_metric_alarm.queue_backlog_age["school-test-events"].metric_name == "ApproximateAgeOfOldestMessage"
    error_message = "Alarm on message age, not queue length."
  }
}

run "the_database_gets_cpu_storage_and_connection_alarms" {
  command = plan
  variables {
    rds_instance_id = "school-test-db"
  }

  assert {
    condition     = toset(keys(aws_cloudwatch_metric_alarm.rds)) == toset(["cpu", "free_storage", "connections"])
    error_message = "Three database alarms."
  }
  assert {
    condition     = aws_cloudwatch_metric_alarm.rds["free_storage"].comparison_operator == "LessThanThreshold" && aws_cloudwatch_metric_alarm.rds["free_storage"].threshold == 5368709120
    error_message = "Free storage alarms when it falls BELOW 5 GiB."
  }
  assert {
    condition     = aws_cloudwatch_metric_alarm.rds["cpu"].dimensions["DBInstanceIdentifier"] == "school-test-db"
    error_message = "Alarms must point at the right instance."
  }
}

run "lambda_errors_are_alarmed" {
  command = plan
  variables {
    lambda_function_names = ["school-test-notification-delivery"]
  }

  assert {
    condition     = aws_cloudwatch_metric_alarm.lambda_errors["school-test-notification-delivery"].metric_name == "Errors" && aws_cloudwatch_metric_alarm.lambda_errors["school-test-notification-delivery"].threshold == 0
    error_message = "Any error in the delivery function raises an alarm."
  }
}

run "the_alarm_name_list_covers_everything" {
  command = plan
  variables {
    dead_letter_queue_names = ["a-dlq"]
    queue_names             = ["a"]
    rds_instance_id         = "db"
    lambda_function_names   = ["fn"]
  }

  assert {
    condition     = length(output.alarm_names) == 1 + 1 + 3 + 1
    error_message = "1 dead-letter + 1 age + 3 database + 1 lambda alarms."
  }
}
