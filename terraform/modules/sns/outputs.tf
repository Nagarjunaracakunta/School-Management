output "topic_arn" {
  description = "ARN of the topic (the SNS_TOPIC_ARN setting, and what IAM policies refer to)."
  value       = aws_sns_topic.this.arn
}

output "topic_name" {
  description = "Name of the topic."
  value       = aws_sns_topic.this.name
}
