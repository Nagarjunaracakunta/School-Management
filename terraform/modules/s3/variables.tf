variable "name" {
  description = "Bucket name (globally unique across all of AWS)."
  type        = string
}

variable "versioning" {
  description = "Keep old versions of overwritten/deleted objects. Lets you roll back a bad deploy."
  type        = bool
  default     = true
}

variable "noncurrent_version_days" {
  description = "Delete old versions after this many days."
  type        = number
  default     = 30
}

variable "force_destroy" {
  description = "Allow Terraform to delete the bucket even if it contains objects. Fine for dev, dangerous in prod."
  type        = bool
  default     = false
}

variable "kms_key_arn" {
  description = "KMS key for encryption. null = S3-managed keys (AES-256)."
  type        = string
  default     = null
}

variable "tags" {
  description = "Extra tags."
  type        = map(string)
  default     = {}
}
