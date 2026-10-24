variable "project" {
  description = "Short project name; the first part of every resource name."
  type        = string
  default     = "school"
}

variable "environment" {
  description = "dev, stage or prod."
  type        = string

  validation {
    condition     = contains(["dev", "stage", "prod"], var.environment)
    error_message = "environment must be one of: dev, stage, prod."
  }
}

variable "aws_region" {
  description = "AWS region for everything in this environment."
  type        = string
  default     = "ap-south-1"
}

variable "allowed_account_ids" {
  description = "The AWS account(s) this environment lives in. Anything else is refused."
  type        = list(string)

  validation {
    condition     = length(var.allowed_account_ids) > 0 && alltrue([for id in var.allowed_account_ids : can(regex("^[0-9]{12}$", id))])
    error_message = "allowed_account_ids must be a non-empty list of 12-digit AWS account ids."
  }
}

variable "owner" {
  description = "Team responsible for this environment (the Owner tag)."
  type        = string
  default     = "platform-team"
}

# ---- network ----------------------------------------------------------------------------------------------------
variable "vpc_cidr" {
  description = "Address range of this environment's VPC (a /16). Each environment uses a different one so they can be connected later."
  type        = string
}

variable "az_count" {
  description = "How many availability zones to spread across."
  type        = number

  validation {
    condition     = var.az_count >= 2 && var.az_count <= 3
    error_message = "az_count must be 2 or 3."
  }
}

variable "nat_mode" {
  description = "none, single or per_az (see the vpc module). Cost versus resilience."
  type        = string
}

variable "enable_flow_logs" {
  description = "Record network connections to CloudWatch Logs."
  type        = bool
}

variable "interface_endpoints" {
  description = "AWS services to reach privately inside the VPC (each costs money per zone)."
  type        = list(string)
  default     = []
}

# ---- container registry -----------------------------------------------------------------------------------------
variable "manage_ecr" {
  description = "Create the ECR repositories in this account. Only ONE environment (dev) owns the registry: images are built once and the others pull them."
  type        = bool
}

variable "ecr_pull_account_ids" {
  description = "Other accounts allowed to pull images from this registry."
  type        = list(string)
  default     = []
}

# ---- database -----------------------------------------------------------------------------------------------------
variable "rds_instance_class" {
  description = "Database machine size, for example db.t4g.micro."
  type        = string
}

variable "rds_allocated_storage_gb" {
  description = "Initial database disk size."
  type        = number
}

variable "rds_max_allocated_storage_gb" {
  description = "The disk grows automatically up to this size."
  type        = number
}

variable "rds_multi_az" {
  description = "Keep a standby database in a second zone."
  type        = bool
}

variable "rds_backup_retention_days" {
  description = "Days of automated backups (point-in-time recovery)."
  type        = number
}

variable "rds_deletion_protection" {
  description = "AWS refuses to delete the database while on."
  type        = bool
}

variable "rds_skip_final_snapshot" {
  description = "Skip the last backup when the database is deleted (dev only)."
  type        = bool
}

variable "rds_performance_insights" {
  description = "Query-level performance monitoring."
  type        = bool
}

variable "secrets_recovery_days" {
  description = "A deleted secret can be restored for this many days (0 = delete at once, dev only)."
  type        = number
}

# ---- messaging and delivery ---------------------------------------------------------------------------------------
variable "alert_emails" {
  description = "People who receive alarm emails. Each must click the confirmation link AWS sends."
  type        = list(string)
  default     = []
}

variable "ses_from_address" {
  description = "Verified sender address for notification emails (AWS emails a link to confirm it). Empty = email delivery disabled, SMS still works."
  type        = string
  default     = ""
}

variable "sms_sender_id" {
  description = "Name shown as the SMS sender where the country allows it (India requires registration first). Empty = AWS default."
  type        = string
  default     = ""
}

variable "delivery_max_concurrency" {
  description = "Most simultaneous delivery-function runs: a brake against flooding SES/SMS limits."
  type        = number
  default     = 10
}

# ---- frontend -----------------------------------------------------------------------------------------------------
variable "frontend_force_destroy" {
  description = "Let Terraform delete the frontend bucket even when it holds files (dev/stage only)."
  type        = bool
}

variable "cloudfront_price_class" {
  description = "Which CloudFront edge locations to use."
  type        = string
  default     = "PriceClass_200"
}

variable "api_origin_domain_name" {
  description = "Host name of the load balancer that serves /api/* (known after Phase 14/15 creates it). null = frontend only."
  type        = string
  default     = null
}

variable "api_origin_protocol" {
  description = "https (needs your own domain and an ACM certificate on the load balancer) or http (dev only, no domain needed: the hop CloudFront to load balancer is unencrypted)."
  type        = string
  default     = "https"
}

variable "domain_aliases" {
  description = "Your own domain names for the portal. Needs acm_certificate_arn."
  type        = list(string)
  default     = []
}

variable "acm_certificate_arn" {
  description = "ACM certificate (in us-east-1) for domain_aliases."
  type        = string
  default     = null
}

# ---- Kubernetes (EKS) ---------------------------------------------------------------------------------------------------
variable "kubernetes_version" {
  description = "Kubernetes minor version, for example 1.34. Pick the newest one AWS still supports with standard (not paid extended) support."
  type        = string
}

variable "eks_public_access_cidrs" {
  description = "Internet addresses allowed to reach the Kubernetes API with kubectl (never 0.0.0.0/0). Empty = API reachable only from inside the VPC."
  type        = list(string)
}

variable "eks_admin_principal_arns" {
  description = "IAM roles/users with cluster-admin rights."
  type        = list(string)
}

variable "node_instance_types" {
  description = "Worker machine types (x86_64)."
  type        = list(string)
}

variable "node_min_size" {
  description = "Fewest worker nodes."
  type        = number
}

variable "node_desired_size" {
  description = "Worker nodes at creation (the autoscaler owns the number afterwards)."
  type        = number
}

variable "node_max_size" {
  description = "Most worker nodes."
  type        = number
}

variable "node_disk_gb" {
  description = "Root disk per node."
  type        = number
  default     = 30
}

variable "ecr_owner_account_id" {
  description = "The AWS account whose registry holds the images (dev). Needed by environments that do NOT own the registry (manage_ecr = false) to know where to pull from."
  type        = string
  default     = ""
}

variable "github_repository" {
  description = "The GitHub repository (OWNER/REPO) whose pipeline may push images. Used only where manage_ecr is true."
  type        = string
  default     = "OWNER/school-management"
}

variable "github_create_oidc_provider" {
  description = "Create the GitHub OIDC identity provider. An account can have only one: set false if another stack already created it."
  type        = bool
  default     = true
}
