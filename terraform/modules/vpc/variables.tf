variable "name" {
  description = "Name prefix for everything in this VPC, for example school-dev."
  type        = string
}

variable "cidr_block" {
  description = "Address range of the whole VPC. Must be a /16: the subnet layout below depends on it."
  type        = string
  default     = "10.0.0.0/16"

  validation {
    condition     = can(cidrnetmask(var.cidr_block)) && endswith(var.cidr_block, "/16")
    error_message = "cidr_block must be a valid IPv4 range ending in /16, for example 10.10.0.0/16."
  }
}

variable "azs" {
  description = "Availability zones to spread across, for example [\"ap-south-1a\", \"ap-south-1b\"]. Two or more, so one zone failing does not take the platform down."
  type        = list(string)

  validation {
    condition     = length(var.azs) >= 2 && length(var.azs) <= 6 && length(var.azs) == length(distinct(var.azs))
    error_message = "azs must contain between 2 and 6 different availability zones."
  }
}

variable "nat_mode" {
  description = <<-EOT
    How private subnets reach the internet (to pull images, call AWS APIs):
      "none"   - no NAT gateway; private subnets are fully offline (cheapest; only VPC endpoints work)
      "single" - one NAT gateway shared by all zones (cheap; if that zone fails, all outbound traffic stops)
      "per_az" - one NAT gateway per zone (resilient; costs one NAT per zone, about USD 32/month each plus data)
  EOT
  type        = string
  default     = "single"

  validation {
    condition     = contains(["none", "single", "per_az"], var.nat_mode)
    error_message = "nat_mode must be one of: none, single, per_az."
  }
}

variable "eks_cluster_name" {
  description = "If set, subnets get the tags the Kubernetes load-balancer controller uses to find them."
  type        = string
  default     = ""
}

variable "enable_s3_endpoint" {
  description = "Add a free S3 gateway endpoint so S3 traffic (including image layers from ECR) skips the NAT gateway."
  type        = bool
  default     = true
}

variable "interface_endpoints" {
  description = <<-EOT
    AWS services to reach privately, without leaving the VPC, for example ["ecr.api", "ecr.dkr", "sqs", "sns", "secretsmanager", "logs", "sts"].
    Each one costs about USD 7/month per zone, so the default is none.
  EOT
  type        = list(string)
  default     = []
}

variable "enable_flow_logs" {
  description = "Record accepted/rejected network connections to CloudWatch Logs (for security investigations)."
  type        = bool
  default     = false
}

variable "flow_logs_retention_days" {
  description = "How long flow logs are kept."
  type        = number
  default     = 30
}

variable "tags" {
  description = "Extra tags for every resource, on top of the provider's default_tags."
  type        = map(string)
  default     = {}
}
