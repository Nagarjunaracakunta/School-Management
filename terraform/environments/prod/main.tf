data "aws_availability_zones" "available" {
  state = "available"
}

# ---- guardrails ---------------------------------------------------------------------------------------------------
# Rules about what an environment may look like. They are checked at PLAN time, so a mistake in terraform.tfvars is
# caught before anything is built. terraform_data is a resource that creates nothing; it only gives us a place to
# attach `precondition` checks.
resource "terraform_data" "guardrails" {
  lifecycle {
    precondition {
      condition     = var.environment != "prod" || var.nat_mode == "per_az"
      error_message = "prod must use nat_mode = per_az: one shared NAT gateway is a single point of failure."
    }
    precondition {
      condition     = var.environment != "prod" || var.az_count == 3
      error_message = "prod must span 3 availability zones."
    }
    precondition {
      condition     = var.environment != "prod" || var.enable_flow_logs
      error_message = "prod must have VPC flow logs enabled (needed for security investigations)."
    }
    precondition {
      condition     = var.environment != "prod" || (var.rds_multi_az && var.rds_deletion_protection && !var.rds_skip_final_snapshot)
      error_message = "prod's database must be Multi-AZ, have deletion protection, and take a final snapshot when deleted."
    }
    precondition {
      condition     = var.environment != "prod" || var.rds_backup_retention_days >= 7
      error_message = "prod must keep at least 7 days of database backups."
    }
    precondition {
      condition     = var.environment != "prod" || (!var.frontend_force_destroy && var.secrets_recovery_days >= 7)
      error_message = "prod must not allow force-deleting the frontend bucket or deleting secrets without a recovery window."
    }
    precondition {
      condition     = var.api_origin_protocol == "https" || var.environment == "dev"
      error_message = "Only dev may use api_origin_protocol = http. stage and prod need a domain and a certificate, so CloudFront reaches the load balancer over TLS."
    }
    precondition {
      condition     = var.environment != "prod" || var.node_min_size >= 2
      error_message = "prod needs at least 2 worker nodes always running, so one failing node does not stop the platform."
    }
    precondition {
      condition     = var.node_min_size <= var.node_desired_size && var.node_desired_size <= var.node_max_size
      error_message = "Node counts must satisfy min <= desired <= max."
    }
    precondition {
      condition     = var.manage_ecr || can(regex("^[0-9]{12}$", var.ecr_owner_account_id))
      error_message = "An environment that does not own the container registry must set ecr_owner_account_id (the account that does: dev)."
    }
    precondition {
      condition     = !var.manage_ecr || length(var.ecr_pull_account_ids) > 0 || var.environment != "dev"
      error_message = "The environment that owns the registry (dev) must list the other accounts allowed to pull from it."
    }
  }
}

# ---- network ------------------------------------------------------------------------------------------------------
module "vpc" {
  source = "../../modules/vpc"

  name                = "${local.name_prefix}-vpc"
  cidr_block          = var.vpc_cidr
  azs                 = local.azs
  nat_mode            = var.nat_mode
  eks_cluster_name    = local.name_prefix # the EKS cluster (Phase 14) will have this name
  enable_flow_logs    = var.enable_flow_logs
  interface_endpoints = var.interface_endpoints

  depends_on = [terraform_data.guardrails] # do not build anything until the guardrails pass
}

# ---- container registry (one environment owns it) ------------------------------------------------------------------
module "ecr" {
  source = "../../modules/ecr"
  count  = var.manage_ecr ? 1 : 0 # count 0 or 1 is the standard way to make a whole module optional

  name_prefix      = var.project
  repositories     = toset(local.ecr_repositories)
  pull_account_ids = var.ecr_pull_account_ids
}
