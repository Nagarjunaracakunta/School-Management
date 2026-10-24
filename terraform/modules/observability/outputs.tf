output "alarm_names" {
  description = "Names of every alarm created."
  value = concat(
    [for a in aws_cloudwatch_metric_alarm.dlq_not_empty : a.alarm_name],
    [for a in aws_cloudwatch_metric_alarm.queue_backlog_age : a.alarm_name],
    [for a in aws_cloudwatch_metric_alarm.rds : a.alarm_name],
    [for a in aws_cloudwatch_metric_alarm.lambda_errors : a.alarm_name],
  )
}
