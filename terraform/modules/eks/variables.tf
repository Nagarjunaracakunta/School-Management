variable "name" {
  description = "Cluster name, for example school-dev. The VPC subnets are already tagged with this name for the load balancer controller."
  type        = string
}

variable "kubernetes_version" {
  description = "Kubernetes minor version, for example 1.34. AWS supports each version for about 14 months, then charges extra for extended support: check `aws eks describe-addon-versions` for what is currently offered and pick the newest standard-support one."
  type        = string

  validation {
    condition     = can(regex("^1\\.[0-9]{2}$", var.kubernetes_version))
    error_message = "kubernetes_version must look like 1.34."
  }
}

variable "vpc_id" {
  description = "VPC of the cluster."
  type        = string
}

variable "subnet_ids" {
  description = "PRIVATE subnets (at least two zones) for the control plane's network interfaces and the worker nodes."
  type        = list(string)

  validation {
    condition     = length(var.subnet_ids) >= 2
    error_message = "EKS needs subnets in at least two availability zones."
  }
}

variable "endpoint_public_access_cidrs" {
  description = <<-EOT
    Internet addresses allowed to reach the Kubernetes API (kubectl). Use your office or home address range, for example
    ["203.0.113.7/32"]. An empty list switches the public endpoint OFF; then the API is reachable only from inside the VPC
    (through a VPN or a bastion). 0.0.0.0/0 (the whole internet) is refused.
  EOT
  type        = list(string)

  validation {
    condition     = !contains(var.endpoint_public_access_cidrs, "0.0.0.0/0")
    error_message = "Do not expose the Kubernetes API to the whole internet (0.0.0.0/0). List the addresses that need kubectl."
  }
  validation {
    condition     = alltrue([for c in var.endpoint_public_access_cidrs : can(cidrnetmask(c))])
    error_message = "endpoint_public_access_cidrs must be valid IPv4 ranges such as 203.0.113.7/32."
  }
}

variable "admin_principal_arns" {
  description = "IAM roles or users that get full cluster-admin rights (people running kubectl, and later the CI/CD role). Everyone else has no access: EKS access entries replace the old aws-auth ConfigMap."
  type        = list(string)

  validation {
    condition     = length(var.admin_principal_arns) > 0 && alltrue([for a in var.admin_principal_arns : can(regex("^arn:aws:iam::[0-9]{12}:(role|user)/.+", a))])
    error_message = "admin_principal_arns must be a non-empty list of IAM role or user ARNs."
  }
}

variable "encrypt_secrets" {
  description = "Encrypt Kubernetes Secret objects in the cluster's database with a dedicated KMS key (envelope encryption)."
  type        = bool
  default     = true
}

variable "log_retention_days" {
  description = "How long control-plane logs (API calls, audit trail, authentication) are kept."
  type        = number
  default     = 30
}

# ---- worker nodes -----------------------------------------------------------------------------------------------------------
variable "node_instance_types" {
  description = "Machine types for the worker nodes, for example [\"t3.medium\"]. x86_64: CI builds linux/amd64 images."
  type        = list(string)
}

variable "node_min_size" {
  description = "Fewest nodes. Use 2 or more where an outage matters, so a single node failing does not stop the platform."
  type        = number
}

variable "node_desired_size" {
  description = "Starting number of nodes. After creation the autoscaler owns this number and Terraform leaves it alone."
  type        = number
}

variable "node_max_size" {
  description = "Most nodes."
  type        = number

  validation {
    condition     = var.node_max_size >= 1
    error_message = "node_max_size must be at least 1."
  }
}

variable "node_disk_gb" {
  description = "Root disk size per node (encrypted)."
  type        = number
  default     = 30
}

# ---- who gets AWS permissions --------------------------------------------------------------------------------------------
variable "pod_identity_associations" {
  description = <<-EOT
    Connect Kubernetes service accounts to IAM roles (EKS Pod Identity), keyed by a name you choose:
      { fee = { namespace = "school-dev", service_account = "fee", role_arn = "arn:aws:iam::...:role/school-dev-fee" } }
    A pod using that service account receives that role's permissions, and no other pod does.
  EOT
  type = map(object({
    namespace       = string
    service_account = string
    role_arn        = string
  }))
  default = {}
}

variable "tags" {
  description = "Extra tags."
  type        = map(string)
  default     = {}
}
