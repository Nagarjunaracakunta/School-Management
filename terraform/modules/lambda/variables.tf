variable "name" {
  description = "Function name, for example school-dev-notification-delivery."
  type        = string
}

variable "source_dir" {
  description = "Folder with the function's code. It is zipped by Terraform; the zip changes (and the function is redeployed) only when a file changes."
  type        = string
}

variable "handler" {
  description = "File and function to call: handler.handler means the function `handler` in handler.py."
  type        = string
  default     = "handler.handler"
}

variable "runtime" {
  description = "Language runtime."
  type        = string
  default     = "python3.12"
}

variable "timeout_seconds" {
  description = "Maximum run time of one invocation."
  type        = number
  default     = 30
}

variable "memory_mb" {
  description = "Memory (CPU scales with it)."
  type        = number
  default     = 128
}

variable "environment" {
  description = "Environment variables. Never put secrets here: they are visible in the console. Read secrets from Secrets Manager at run time."
  type        = map(string)
  default     = {}
}

variable "statements" {
  description = "What the function may do, besides writing its own logs. Explicit actions and resources only."
  type = list(object({
    sid       = string
    actions   = list(string)
    resources = list(string)
  }))
  default = []

  validation {
    condition     = alltrue(flatten([for s in var.statements : concat([for a in s.actions : !endswith(a, "*")], [for r in s.resources : !endswith(r, "*")])]))
    error_message = "No wildcard actions or resources: list exactly what the function needs."
  }
}

variable "allow_sms_publish" {
  description = "Let the function send text messages to phone numbers (the one permission that cannot be scoped to a resource). It is paired with a Deny on all SNS topics."
  type        = bool
  default     = false
}

variable "sns_trigger" {
  description = <<-EOT
    Invoke the function for messages published to an SNS topic:  { topic_arn = ..., filter_policy = "{...}" }.
    filter_policy is optional JSON; only messages whose attributes match are delivered.
    This is an OBJECT (set or null) rather than a bare ARN on purpose: whether the trigger exists must be known when
    Terraform plans, but a topic created in the same run has no ARN yet. "Is this object null?" is always known.
  EOT
  type = object({
    topic_arn     = string
    filter_policy = optional(string)
  })
  default = null
}

variable "failure_queue" {
  description = "If set ({ arn = ... }), an invocation that still fails after the automatic retries is written to this queue instead of being lost. An object for the same reason as sns_trigger."
  type = object({
    arn = string
  })
  default = null
}

variable "retry_attempts" {
  description = "Automatic retries after a failed asynchronous invocation (0-2)."
  type        = number
  default     = 2
}

variable "log_retention_days" {
  description = "How long the function's logs are kept."
  type        = number
  default     = 30
}

variable "reserved_concurrency" {
  description = "Maximum simultaneous invocations (also a brake on cost and on hammering a downstream service). null = unreserved."
  type        = number
  default     = null
}

variable "tags" {
  description = "Extra tags."
  type        = map(string)
  default     = {}
}
