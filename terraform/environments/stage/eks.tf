# ---- the Kubernetes cluster ---------------------------------------------------------------------------------------------------
locals {
  # Which Kubernetes service account gets which IAM role. A pod running as service account "fee" receives the fee role's
  # permissions and nothing else. The Helm charts (Phase 15) create service accounts with exactly these names, in this namespace.
  pod_identity_associations = {
    for service, role_arn in module.pod_roles.role_arns : service => {
      namespace       = local.kubernetes_namespace
      service_account = service
      role_arn        = role_arn
    }
  }
}

module "eks" {
  source = "../../modules/eks"

  name                         = local.name_prefix
  kubernetes_version           = var.kubernetes_version
  vpc_id                       = module.vpc.vpc_id
  subnet_ids                   = module.vpc.private_subnet_ids
  endpoint_public_access_cidrs = var.eks_public_access_cidrs
  admin_principal_arns         = var.eks_admin_principal_arns

  node_instance_types = var.node_instance_types
  node_min_size       = var.node_min_size
  node_desired_size   = var.node_desired_size
  node_max_size       = var.node_max_size
  node_disk_gb        = var.node_disk_gb

  pod_identity_associations = local.pod_identity_associations

  depends_on = [terraform_data.guardrails]
}

# The database's firewall had NO rules (Phase 13). This is the one rule that opens it: PostgreSQL traffic, and only from the
# cluster's own security group. Not from the VPC, not from a CIDR range, not from the internet.
resource "aws_vpc_security_group_ingress_rule" "database_from_cluster" {
  security_group_id            = module.rds.security_group_id
  referenced_security_group_id = module.eks.cluster_security_group_id
  ip_protocol                  = "tcp"
  from_port                    = 5432
  to_port                      = 5432
  description                  = "PostgreSQL from the Kubernetes cluster"
}
