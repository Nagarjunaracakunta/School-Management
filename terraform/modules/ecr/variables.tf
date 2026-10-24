variable "name_prefix" {
  description = "Prefix for repository names. With \"school\" the repositories are school/auth, school/fee, ..."
  type        = string
  default     = "school"
}

variable "repositories" {
  description = "Repositories to create, one per deployable image."
  type        = set(string)

  validation {
    condition     = length(var.repositories) > 0 && alltrue([for r in var.repositories : can(regex("^[a-z0-9]+([._-][a-z0-9]+)*$", r))])
    error_message = "repositories must be a non-empty set of lower-case names (letters, digits and . _ - only)."
  }
}

variable "image_tag_mutability" {
  description = "IMMUTABLE means a tag can never be pointed at a different image, so a tag always identifies exactly one build."
  type        = string
  default     = "IMMUTABLE"

  validation {
    condition     = contains(["IMMUTABLE", "MUTABLE"], var.image_tag_mutability)
    error_message = "image_tag_mutability must be IMMUTABLE or MUTABLE."
  }
}

variable "scan_on_push" {
  description = "Scan each pushed image for known vulnerabilities."
  type        = bool
  default     = true
}

variable "kms_key_arn" {
  description = "Encrypt images with this KMS key. null uses the AWS-managed AES-256 default."
  type        = string
  default     = null
}

variable "untagged_expire_days" {
  description = "Delete untagged images (leftovers of re-pushes) after this many days."
  type        = number
  default     = 7
}

variable "keep_last_images" {
  description = "Keep at most this many images per repository; older ones are deleted so storage cost stays flat."
  type        = number
  default     = 30
}

variable "pull_account_ids" {
  description = "Other AWS accounts allowed to PULL images. Lets stage and prod run the image dev built, instead of rebuilding it."
  type        = list(string)
  default     = []

  validation {
    condition     = alltrue([for id in var.pull_account_ids : can(regex("^[0-9]{12}$", id))])
    error_message = "pull_account_ids must be 12-digit AWS account ids."
  }
}

variable "tags" {
  description = "Extra tags for every resource."
  type        = map(string)
  default     = {}
}
