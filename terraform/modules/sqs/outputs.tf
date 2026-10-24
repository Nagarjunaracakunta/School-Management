output "queue_url" {
  description = "URL services send to / receive from (goes into the SQS_QUEUE_URL setting)."
  value       = aws_sqs_queue.main.url
}

output "queue_arn" {
  description = "ARN of the main queue (for IAM policies)."
  value       = aws_sqs_queue.main.arn
}

output "queue_name" {
  description = "Name of the main queue (for CloudWatch alarms)."
  value       = aws_sqs_queue.main.name
}

output "dlq_url" {
  description = "URL of the dead-letter queue."
  value       = aws_sqs_queue.dlq.url
}

output "dlq_arn" {
  description = "ARN of the dead-letter queue."
  value       = aws_sqs_queue.dlq.arn
}

output "dlq_name" {
  description = "Name of the dead-letter queue (for CloudWatch alarms)."
  value       = aws_sqs_queue.dlq.name
}
