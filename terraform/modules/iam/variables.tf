variable "name_prefix" {
  description = "Roles are named <name_prefix>-<key>, for example school-dev-fee."
  type        = string
}

variable "roles" {
  description = <<-EOT
    One IAM role per Kubernetes service, keyed by service name. Each role lists exactly what it may do:
      statements = [{ sid = "SendEvents", actions = ["sqs:SendMessage"], resources = [<one queue ARN>] }]
    The module REFUSES any action or resource that ends in a wildcard (*): least privilege is enforced here, in code,
    not left to code review.
  EOT
  type = map(object({
    description = string
    statements = list(object({
      sid       = string
      actions   = list(string)
      resources = list(string)
    }))
  }))

  validation {
    condition = alltrue(flatten([
      for r in values(var.roles) : [
        for s in r.statements : [
          for a in s.actions : !endswith(a, "*")
        ]
      ]
    ]))
    error_message = "IAM actions must be listed explicitly: a wildcard action (for example \"sqs:*\" or \"*\") is not allowed."
  }

  validation {
    condition = alltrue(flatten([
      for r in values(var.roles) : [
        for s in r.statements : [
          for x in s.resources : !endswith(x, "*")
        ]
      ]
    ]))
    error_message = "IAM resources must be listed explicitly: a wildcard resource (for example \"*\" or \"arn:...:*\") is not allowed."
  }

  validation {
    condition     = alltrue(flatten([for r in values(var.roles) : [for s in r.statements : can(regex("^[A-Za-z0-9]+$", s.sid))]]))
    error_message = "A statement sid may contain only letters and digits (an IAM rule)."
  }

  validation {
    condition     = alltrue([for r in values(var.roles) : length(r.statements) > 0])
    error_message = "Every role needs at least one statement."
  }
}

variable "tags" {
  description = "Extra tags."
  type        = map(string)
  default     = {}
}
