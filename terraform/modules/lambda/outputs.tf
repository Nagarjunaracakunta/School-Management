output "function_name" {
  description = "Function name (for alarms and log queries)."
  value       = aws_lambda_function.this.function_name
}

output "function_arn" {
  description = "Function ARN."
  value       = aws_lambda_function.this.arn
}

output "role_arn" {
  description = "The function's execution role."
  value       = aws_iam_role.this.arn
}

output "log_group_name" {
  description = "CloudWatch log group."
  value       = aws_cloudwatch_log_group.this.name
}

output "subscription_arns" {
  description = "The SNS subscription (a list with one entry, or empty when there is no trigger)."
  value       = aws_sns_topic_subscription.this[*].arn
}
