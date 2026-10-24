variable "project" {
  description = "Short project name, used as the first part of every resource name."
  type        = string
  default     = "school"
}

variable "environment" {
  description = "Which environment's AWS account this state bucket lives in."
  type        = string

  validation {
    condition     = contains(["dev", "stage", "prod"], var.environment)
    error_message = "environment must be one of: dev, stage, prod."
  }
}

variable "aws_region" {
  description = "Region for the state bucket (and for the environment's resources)."
  type        = string
  default     = "ap-south-1"
}

variable "allowed_account_ids" {
  description = "AWS account ids this configuration may run against. A safety net against applying to the wrong account."
  type        = list(string)

  validation {
    condition     = length(var.allowed_account_ids) > 0 && alltrue([for id in var.allowed_account_ids : can(regex("^[0-9]{12}$", id))])
    error_message = "allowed_account_ids must be a non-empty list of 12-digit AWS account ids."
  }
}

variable "owner" {
  description = "Team or person responsible for these resources (shown in the Owner tag)."
  type        = string
  default     = "platform-team"
}

variable "noncurrent_version_retention_days" {
  description = "How long old versions of the state file are kept. They are the way back from a bad apply."
  type        = number
  default     = 90
}
