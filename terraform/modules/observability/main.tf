locals {
  actions = [var.alarm_topic_arn]
}

# ---- queues ---------------------------------------------------------------------------------------------------------------
# A message in a dead-letter queue means a message failed every retry: someone must look. This is why there is no
# "DLQ alert" Lambda: an alarm does the same job with no code to maintain.
resource "aws_cloudwatch_metric_alarm" "dlq_not_empty" {
  for_each = var.dead_letter_queue_names

  alarm_name          = "${var.name}-dlq-not-empty-${each.key}"
  alarm_description   = "Messages are waiting in the dead-letter queue ${each.key}. Inspect them and fix or discard (see docs/runbooks)."
  namespace           = "AWS/SQS"
  metric_name         = "ApproximateNumberOfMessagesVisible"
  dimensions          = { QueueName = each.key }
  statistic           = "Maximum"
  period              = 60
  evaluation_periods  = 1
  threshold           = 0
  comparison_operator = "GreaterThanThreshold"
  treat_missing_data  = "notBreaching" # SQS publishes no data when idle; that is fine, not an outage
  alarm_actions       = local.actions
  ok_actions          = local.actions

  tags = var.tags
}

resource "aws_cloudwatch_metric_alarm" "queue_backlog_age" {
  for_each = var.queue_names

  alarm_name          = "${var.name}-queue-stuck-${each.key}"
  alarm_description   = "The oldest message in ${each.key} is older than ${var.queue_max_age_seconds}s: the consumer is down or too slow."
  namespace           = "AWS/SQS"
  metric_name         = "ApproximateAgeOfOldestMessage"
  dimensions          = { QueueName = each.key }
  statistic           = "Maximum"
  period              = 300
  evaluation_periods  = 2
  threshold           = var.queue_max_age_seconds
  comparison_operator = "GreaterThanThreshold"
  treat_missing_data  = "notBreaching"
  alarm_actions       = local.actions
  ok_actions          = local.actions

  tags = var.tags
}

# ---- database -------------------------------------------------------------------------------------------------------------
resource "aws_cloudwatch_metric_alarm" "rds" {
  for_each = var.rds_instance_id == null ? {} : {
    cpu = {
      metric    = "CPUUtilization"
      statistic = "Average"
      threshold = var.rds_cpu_percent
      operator  = "GreaterThanThreshold"
      periods   = 3
      text      = "CPU above ${var.rds_cpu_percent}% for 15 minutes"
    }
    free_storage = {
      metric    = "FreeStorageSpace"
      statistic = "Minimum"
      threshold = var.rds_free_storage_bytes
      operator  = "LessThanThreshold"
      periods   = 1
      text      = "free disk space is below ${var.rds_free_storage_bytes / 1073741824} GiB"
    }
    connections = {
      metric    = "DatabaseConnections"
      statistic = "Maximum"
      threshold = var.rds_connections
      operator  = "GreaterThanThreshold"
      periods   = 2
      text      = "more than ${var.rds_connections} open connections"
    }
  }

  alarm_name          = "${var.name}-db-${each.key}"
  alarm_description   = "Database ${var.rds_instance_id}: ${each.value.text}"
  namespace           = "AWS/RDS"
  metric_name         = each.value.metric
  dimensions          = { DBInstanceIdentifier = var.rds_instance_id }
  statistic           = each.value.statistic
  period              = 300
  evaluation_periods  = each.value.periods
  threshold           = each.value.threshold
  comparison_operator = each.value.operator
  treat_missing_data  = "missing"
  alarm_actions       = local.actions
  ok_actions          = local.actions

  tags = var.tags
}

# ---- functions ------------------------------------------------------------------------------------------------------------
resource "aws_cloudwatch_metric_alarm" "lambda_errors" {
  for_each = var.lambda_function_names

  alarm_name          = "${var.name}-lambda-errors-${each.key}"
  alarm_description   = "The function ${each.key} reported errors. Notifications may not have been delivered."
  namespace           = "AWS/Lambda"
  metric_name         = "Errors"
  dimensions          = { FunctionName = each.key }
  statistic           = "Sum"
  period              = 300
  evaluation_periods  = 1
  threshold           = 0
  comparison_operator = "GreaterThanThreshold"
  treat_missing_data  = "notBreaching"
  alarm_actions       = local.actions
  ok_actions          = local.actions

  tags = var.tags
}
