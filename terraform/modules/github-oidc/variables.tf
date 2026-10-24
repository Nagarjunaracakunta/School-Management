variable "name_prefix" {
  description = "The role is named <name_prefix>-github-ecr-push, for example school-dev-github-ecr-push."
  type        = string
}

variable "github_repository" {
  description = "The ONLY repository allowed to assume the role, as OWNER/REPO."
  type        = string

  validation {
    condition     = can(regex("^[A-Za-z0-9-]+/[A-Za-z0-9._-]+$", var.github_repository))
    error_message = "github_repository must look like OWNER/REPO."
  }
}

variable "github_environment" {
  description = "The GitHub Environment whose jobs may assume the role. Its protection rules (main branch only, reviewers) are what AWS trusts."
  type        = string
  default     = "registry-push"
}

variable "create_provider" {
  description = "Create the account-wide GitHub OIDC identity provider. An AWS account can have only ONE; set false when it already exists."
  type        = bool
  default     = true
}

variable "ecr_repository_arns" {
  description = "The repositories the image-push role may push to. Empty = no image-push role (an environment that does not own the registry)."
  type        = list(string)
  default     = []

  validation {
    condition     = alltrue([for a in var.ecr_repository_arns : !endswith(a, "*")])
    error_message = "List the repositories explicitly: no wildcards."
  }
}

variable "frontend_github_environment" {
  description = "The GitHub Environment whose jobs may deploy the website in THIS AWS account (for example frontend-dev)."
  type        = string
  default     = "frontend"
}

variable "create_frontend_deploy_role" {
  description = "Create the website-deploy role. A plain true/false on purpose: Terraform must know at plan time how many roles to create, and the bucket's ARN is not known until it exists."
  type        = bool
  default     = false
}

variable "frontend_bucket_arn" {
  description = "The website bucket. Required when create_frontend_deploy_role is true."
  type        = string
  default     = null
}

variable "frontend_distribution_arn" {
  description = "The CloudFront distribution to invalidate after a deploy. Required when create_frontend_deploy_role is true."
  type        = string
  default     = null
}

variable "tags" {
  description = "Extra tags for every resource."
  type        = map(string)
  default     = {}
}
