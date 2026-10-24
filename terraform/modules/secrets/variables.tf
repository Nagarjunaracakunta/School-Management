variable "name_prefix" {
  description = "Path prefix for secret names, for example school/dev. Every secret is <prefix>/<kind>/<name>."
  type        = string
}

variable "services" {
  description = "Services that get database logins."
  type        = set(string)
}

variable "db_host" {
  description = "Database host name (from the rds module)."
  type        = string
}

variable "db_port" {
  description = "Database port."
  type        = number
  default     = 5432
}

variable "db_name" {
  description = "Database name."
  type        = string
}

variable "credentials_version" {
  description = "Change this number to generate NEW passwords for every service and write them to Secrets Manager (rotation by hand). Leave it alone otherwise."
  type        = number
  default     = 1
}

variable "recovery_window_days" {
  description = "A deleted secret can be restored for this many days (7-30). 0 deletes immediately: for dev only."
  type        = number
  default     = 7

  validation {
    condition     = var.recovery_window_days == 0 || (var.recovery_window_days >= 7 && var.recovery_window_days <= 30)
    error_message = "recovery_window_days must be 0, or between 7 and 30."
  }
}

variable "kms_key_id" {
  description = "KMS key to encrypt secrets. null uses the AWS-managed Secrets Manager key."
  type        = string
  default     = null
}

variable "tags" {
  description = "Extra tags."
  type        = map(string)
  default     = {}
}
