variable "name" {
  description = "Instance identifier, for example school-dev-db."
  type        = string
}

variable "vpc_id" {
  description = "VPC to place the database security group in."
  type        = string
}

variable "subnet_ids" {
  description = "Database subnets (at least two, in different availability zones)."
  type        = list(string)

  validation {
    condition     = length(var.subnet_ids) >= 2
    error_message = "RDS needs subnets in at least two availability zones."
  }
}

variable "engine_version" {
  description = "PostgreSQL major version. AWS picks the newest minor and applies minor upgrades itself."
  type        = string
  default     = "16"
}

variable "instance_class" {
  description = "Machine size, for example db.t4g.micro (dev) or db.t4g.medium."
  type        = string
}

variable "allocated_storage_gb" {
  description = "Initial disk size."
  type        = number
  default     = 20
}

variable "max_allocated_storage_gb" {
  description = "RDS grows the disk automatically up to this size. Disks cannot shrink, so this is a ceiling, not a target."
  type        = number
  default     = 100
}

variable "multi_az" {
  description = "Keep a standby copy in another zone and fail over to it automatically (doubles the instance cost)."
  type        = bool
  default     = false
}

variable "backup_retention_days" {
  description = "Automated backups kept for this many days (point-in-time recovery inside this window). 0 disables backups."
  type        = number
  default     = 7

  validation {
    condition     = var.backup_retention_days >= 0 && var.backup_retention_days <= 35
    error_message = "backup_retention_days must be between 0 and 35."
  }
}

variable "deletion_protection" {
  description = "AWS refuses to delete the instance while this is on."
  type        = bool
  default     = false
}

variable "skip_final_snapshot" {
  description = "On deletion, skip the last backup. Fine for dev; never for production."
  type        = bool
  default     = true
}

variable "performance_insights" {
  description = "Query-level performance monitoring (7 days free)."
  type        = bool
  default     = false
}

variable "kms_key_id" {
  description = "KMS key for storage encryption. null uses the AWS-managed RDS key."
  type        = string
  default     = null
}

variable "log_retention_days" {
  description = "How long database logs are kept in CloudWatch."
  type        = number
  default     = 30
}

variable "db_name" {
  description = "Name of the database inside the instance."
  type        = string
  default     = "school"
}

variable "master_username" {
  description = "Administrator login. Only used by the bootstrap job that creates the per-service roles."
  type        = string
  default     = "school_admin"
}

variable "tags" {
  description = "Extra tags."
  type        = map(string)
  default     = {}
}
