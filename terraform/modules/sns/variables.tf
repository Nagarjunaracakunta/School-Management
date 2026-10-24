variable "name" {
  description = "Topic name, for example school-dev-notifications."
  type        = string
}

variable "kms_master_key_id" {
  description = "KMS key (or alias such as alias/aws/sns) to encrypt messages. null = not encrypted. CloudWatch alarms cannot publish to a topic encrypted with an AWS-managed key, so the alerts topic leaves this null."
  type        = string
  default     = null
}

variable "allow_cloudwatch_alarms" {
  description = "Let CloudWatch alarms in this account publish to the topic (for an alerts topic)."
  type        = bool
  default     = false
}

variable "subscriptions" {
  description = <<-EOT
    Who receives messages, keyed by a name you choose (for example "ops-email" or "delivery-lambda"). The key must be known
    at plan time, which is why this is a map and not a list.
      protocol             email, lambda, sqs, https ...
      endpoint             address, function ARN, queue ARN ...
      filter_policy        optional JSON; only matching messages are delivered (matched against message attributes)
      raw_message_delivery optional; true for sqs/https to skip the SNS envelope
    An email subscription stays "pending" until the recipient clicks the confirmation link.
  EOT
  type = map(object({
    protocol             = string
    endpoint             = string
    filter_policy        = optional(string)
    raw_message_delivery = optional(bool, false)
  }))
  default = {}
}

variable "tags" {
  description = "Extra tags."
  type        = map(string)
  default     = {}
}
