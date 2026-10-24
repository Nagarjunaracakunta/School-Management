variable "name" {
  description = "Queue name, for example school-dev-events. The dead-letter queue is <name>-dlq."
  type        = string
}

variable "visibility_timeout_seconds" {
  description = "How long a received message stays hidden from other consumers. Must be longer than the time to process one message."
  type        = number
  default     = 60
}

variable "message_retention_days" {
  description = "How long an unprocessed message is kept before SQS deletes it."
  type        = number
  default     = 4
}

variable "dlq_retention_days" {
  description = "How long failed messages wait in the dead-letter queue for a human. Longer than the main queue, so they survive a long weekend."
  type        = number
  default     = 14
}

variable "max_receive_count" {
  description = "After this many failed receives a message moves to the dead-letter queue instead of being retried forever."
  type        = number
  default     = 3

  validation {
    condition     = var.max_receive_count >= 1 && var.max_receive_count <= 20
    error_message = "max_receive_count must be between 1 and 20."
  }
}

variable "kms_master_key_id" {
  description = "Customer-managed KMS key for encryption. null uses SQS-managed encryption (free, no key to manage)."
  type        = string
  default     = null
}

variable "tags" {
  description = "Extra tags."
  type        = map(string)
  default     = {}
}
