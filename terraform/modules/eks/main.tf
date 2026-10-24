data "aws_partition" "current" {}
data "aws_caller_identity" "current" {}

locals {
  public_endpoint = length(var.endpoint_public_access_cidrs) > 0

  # Settings for individual add-ons. NetworkPolicy objects are only ENFORCED if the CNI is told to; otherwise Kubernetes
  # accepts them and nothing happens, which looks secure and is not.
  addon_configuration = {
    "vpc-cni" = jsonencode({ enableNetworkPolicy = "true" })
  }
  node_policies = [
    "AmazonEKSWorkerNodePolicy",          # the node joins the cluster
    "AmazonEKS_CNI_Policy",               # pod networking (assign IP addresses to pods)
    "AmazonEC2ContainerRegistryReadOnly", # pull images from ECR, including another account's (dev's) registry
    "AmazonSSMManagedInstanceCore",       # shell access through AWS Systems Manager: no SSH keys, no open port 22
  ]
}

# ---- encryption key for Kubernetes Secret objects --------------------------------------------------------------------------
resource "aws_kms_key" "secrets" {
  count = var.encrypt_secrets ? 1 : 0

  description             = "Encrypts Kubernetes Secrets in the ${var.name} cluster"
  enable_key_rotation     = true # a new key version every year, automatically
  deletion_window_in_days = 7

  tags = merge(var.tags, { Name = "${var.name}-eks-secrets" })
}

resource "aws_kms_alias" "secrets" {
  count = var.encrypt_secrets ? 1 : 0

  name          = "alias/${var.name}-eks-secrets"
  target_key_id = aws_kms_key.secrets[0].key_id
}

# ---- control plane logs ----------------------------------------------------------------------------------------------------
# Created by us so the retention is set. EKS would otherwise create the group itself and keep logs forever.
resource "aws_cloudwatch_log_group" "cluster" {
  name              = "/aws/eks/${var.name}/cluster"
  retention_in_days = var.log_retention_days

  tags = var.tags
}

# ---- the cluster's own IAM role ------------------------------------------------------------------------------------------------
resource "aws_iam_role" "cluster" {
  name = "${var.name}-eks-cluster"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "eks.amazonaws.com" }
      Action    = ["sts:AssumeRole", "sts:TagSession"]
    }]
  })

  tags = var.tags
}

resource "aws_iam_role_policy_attachment" "cluster" {
  role       = aws_iam_role.cluster.name
  policy_arn = "arn:${data.aws_partition.current.partition}:iam::aws:policy/AmazonEKSClusterPolicy"
}

resource "aws_iam_role_policy" "cluster_kms" {
  count = var.encrypt_secrets ? 1 : 0

  name = "use-secrets-key"
  role = aws_iam_role.cluster.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Sid      = "UseTheSecretsKey"
      Effect   = "Allow"
      Action   = ["kms:Encrypt", "kms:Decrypt", "kms:ListGrants", "kms:DescribeKey"]
      Resource = [aws_kms_key.secrets[0].arn]
    }]
  })
}

# ---- the cluster ------------------------------------------------------------------------------------------------------------
resource "aws_eks_cluster" "this" {
  name     = var.name
  version  = var.kubernetes_version
  role_arn = aws_iam_role.cluster.arn

  vpc_config {
    subnet_ids              = var.subnet_ids
    endpoint_private_access = true # pods and nodes always reach the API privately, inside the VPC
    endpoint_public_access  = local.public_endpoint
    public_access_cidrs     = local.public_endpoint ? var.endpoint_public_access_cidrs : null
  }

  # Who may use kubectl is decided by EKS "access entries" (below), not by the old aws-auth ConfigMap that anyone with
  # edit rights in kube-system could break. We also do NOT auto-grant admin to whoever happened to create the cluster.
  access_config {
    authentication_mode                         = "API"
    bootstrap_cluster_creator_admin_permissions = false
  }

  dynamic "encryption_config" {
    for_each = var.encrypt_secrets ? [1] : []

    content {
      resources = ["secrets"]

      provider {
        key_arn = aws_kms_key.secrets[0].arn
      }
    }
  }

  enabled_cluster_log_types = ["api", "audit", "authenticator", "controllerManager", "scheduler"]

  tags = merge(var.tags, { Name = var.name })

  depends_on = [
    aws_iam_role_policy_attachment.cluster,
    aws_iam_role_policy.cluster_kms,
    aws_cloudwatch_log_group.cluster, # our retention setting must exist before EKS starts logging
  ]
}

# ---- who may use kubectl -----------------------------------------------------------------------------------------------------
resource "aws_eks_access_entry" "admin" {
  for_each = toset(var.admin_principal_arns)

  cluster_name  = aws_eks_cluster.this.name
  principal_arn = each.value
  type          = "STANDARD"
}

resource "aws_eks_access_policy_association" "admin" {
  for_each = aws_eks_access_entry.admin

  cluster_name  = aws_eks_cluster.this.name
  principal_arn = each.value.principal_arn
  policy_arn    = "arn:${data.aws_partition.current.partition}:eks::aws:cluster-access-policy/AmazonEKSClusterAdminPolicy"

  access_scope {
    type = "cluster"
  }
}

# ---- worker nodes ----------------------------------------------------------------------------------------------------------------
resource "aws_iam_role" "node" {
  name = "${var.name}-eks-node"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "ec2.amazonaws.com" }
      Action    = "sts:AssumeRole"
    }]
  })

  tags = var.tags
}

resource "aws_iam_role_policy_attachment" "node" {
  for_each = toset(local.node_policies)

  role       = aws_iam_role.node.name
  policy_arn = "arn:${data.aws_partition.current.partition}:iam::aws:policy/${each.value}"
}

# The recipe for each node (EC2 launch template). Two security settings are only possible here:
resource "aws_launch_template" "node" {
  name_prefix = "${var.name}-node-"

  metadata_options {
    http_endpoint = "enabled"
    http_tokens   = "required" # IMDSv2 only: a stolen-URL (SSRF) bug cannot read the node's credentials
    # One network hop: a pod (which is one hop further away) cannot reach the node's credentials at all. Pods get their
    # AWS permissions from EKS Pod Identity, so they have no reason to try.
    http_put_response_hop_limit = 1
  }

  block_device_mappings {
    device_name = "/dev/xvda"

    ebs {
      volume_size           = var.node_disk_gb
      volume_type           = "gp3"
      encrypted             = true
      delete_on_termination = true
    }
  }

  tag_specifications {
    resource_type = "instance"
    tags          = merge(var.tags, { Name = "${var.name}-node" })
  }

  lifecycle {
    create_before_destroy = true
  }
}

resource "aws_eks_node_group" "this" {
  cluster_name    = aws_eks_cluster.this.name
  node_group_name = "${var.name}-general"
  node_role_arn   = aws_iam_role.node.arn
  subnet_ids      = var.subnet_ids

  ami_type       = "AL2023_x86_64_STANDARD" # Amazon Linux 2023; AWS patches and rolls the AMI
  instance_types = var.node_instance_types
  capacity_type  = "ON_DEMAND"

  launch_template {
    id      = aws_launch_template.node.id
    version = aws_launch_template.node.latest_version
  }

  scaling_config {
    min_size     = var.node_min_size
    desired_size = var.node_desired_size
    max_size     = var.node_max_size
  }

  update_config {
    max_unavailable = 1 # replace nodes one at a time during an upgrade
  }

  tags = var.tags

  lifecycle {
    # Once the cluster autoscaler (or you) changes the node count, Terraform must not fight it back to the number in the code.
    ignore_changes = [scaling_config[0].desired_size]
  }

  depends_on = [aws_iam_role_policy_attachment.node]
}

# ---- cluster add-ons managed by AWS -----------------------------------------------------------------------------------------------
data "aws_eks_addon_version" "this" {
  for_each = toset(["vpc-cni", "kube-proxy", "coredns", "eks-pod-identity-agent"])

  addon_name         = each.value
  kubernetes_version = aws_eks_cluster.this.version
  most_recent        = true
}

resource "aws_eks_addon" "this" {
  for_each = data.aws_eks_addon_version.this

  cluster_name                = aws_eks_cluster.this.name
  addon_name                  = each.key
  addon_version               = each.value.version
  configuration_values        = lookup(local.addon_configuration, each.key, null)
  resolve_conflicts_on_create = "OVERWRITE"
  resolve_conflicts_on_update = "OVERWRITE"

  tags = var.tags

  # These run as pods, so they need nodes to land on
  depends_on = [aws_eks_node_group.this]
}

# ---- Pod Identity: which service account gets which IAM role -------------------------------------------------------------------------
resource "aws_eks_pod_identity_association" "this" {
  for_each = var.pod_identity_associations

  cluster_name    = aws_eks_cluster.this.name
  namespace       = each.value.namespace
  service_account = each.value.service_account
  role_arn        = each.value.role_arn

  tags = var.tags

  depends_on = [aws_eks_addon.this] # the agent that hands out the credentials must exist
}

# ---- the AWS Load Balancer Controller's permissions ---------------------------------------------------------------------------------
# The controller (installed with Helm in Phase 15) turns a Kubernetes Ingress into an Application Load Balancer. It needs
# broad ELB/EC2 permissions that AWS publishes as a ready-made policy. We vendor that file (pinned to a release, see
# policies/aws-load-balancer-controller.version) instead of rewriting it. This is the one place in the project where a policy
# contains wildcard resources; that is inherent to the controller and the reason it does not go through the iam module.
resource "aws_iam_role" "load_balancer_controller" {
  name = "${var.name}-aws-load-balancer-controller"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "pods.eks.amazonaws.com" }
      Action    = ["sts:AssumeRole", "sts:TagSession"]
    }]
  })

  tags = var.tags
}

resource "aws_iam_role_policy" "load_balancer_controller" {
  name   = "load-balancer-controller"
  role   = aws_iam_role.load_balancer_controller.id
  policy = file("${path.module}/policies/aws-load-balancer-controller.json")
}

resource "aws_eks_pod_identity_association" "load_balancer_controller" {
  cluster_name    = aws_eks_cluster.this.name
  namespace       = "kube-system"
  service_account = "aws-load-balancer-controller"
  role_arn        = aws_iam_role.load_balancer_controller.arn

  tags = var.tags

  depends_on = [aws_eks_addon.this]
}
