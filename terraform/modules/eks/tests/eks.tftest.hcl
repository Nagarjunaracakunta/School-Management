mock_provider "aws" {
  mock_data "aws_partition" {
    defaults = {
      partition = "aws"
    }
  }
  mock_data "aws_caller_identity" {
    defaults = {
      account_id = "123456789012"
    }
  }
}

variables {
  name                         = "school-test"
  kubernetes_version           = "1.34"
  vpc_id                       = "vpc-0123456789abcdef0"
  subnet_ids                   = ["subnet-aaaa", "subnet-bbbb"]
  endpoint_public_access_cidrs = ["203.0.113.7/32"]
  admin_principal_arns         = ["arn:aws:iam::123456789012:role/PlatformAdmins"]
  node_instance_types          = ["t3.medium"]
  node_min_size                = 2
  node_desired_size            = 2
  node_max_size                = 4
}

run "the_cluster_uses_access_entries_and_trusts_nobody_by_default" {
  command = plan

  assert {
    condition     = aws_eks_cluster.this.access_config[0].authentication_mode == "API"
    error_message = "Use EKS access entries, not the aws-auth ConfigMap."
  }
  assert {
    condition     = aws_eks_cluster.this.access_config[0].bootstrap_cluster_creator_admin_permissions == false
    error_message = "Whoever ran Terraform must not silently become cluster admin: admins are named explicitly."
  }
  assert {
    condition     = aws_eks_cluster.this.version == "1.34" && aws_eks_cluster.this.vpc_config[0].endpoint_private_access
    error_message = "The version follows the input and the API is always reachable privately."
  }
}

run "control_plane_logs_cover_audit_and_authentication" {
  command = plan

  assert {
    condition     = toset(aws_eks_cluster.this.enabled_cluster_log_types) == toset(["api", "audit", "authenticator", "controllerManager", "scheduler"])
    error_message = "All five control-plane log types should be on: the audit log is how you answer 'who did that?'."
  }
  assert {
    condition     = aws_cloudwatch_log_group.cluster.name == "/aws/eks/school-test/cluster" && aws_cloudwatch_log_group.cluster.retention_in_days == 30
    error_message = "We create the log group so the retention is set."
  }
}

run "the_public_api_is_limited_to_the_listed_addresses" {
  command = plan

  assert {
    condition     = aws_eks_cluster.this.vpc_config[0].endpoint_public_access && aws_eks_cluster.this.vpc_config[0].public_access_cidrs == toset(["203.0.113.7/32"])
    error_message = "Only the given address may reach the Kubernetes API from the internet."
  }
}

run "an_empty_list_switches_the_public_endpoint_off" {
  command = plan
  variables {
    endpoint_public_access_cidrs = []
  }

  assert {
    condition     = aws_eks_cluster.this.vpc_config[0].endpoint_public_access == false
    error_message = "No addresses means no public endpoint at all."
  }
}

run "the_whole_internet_is_refused" {
  command = plan
  variables {
    endpoint_public_access_cidrs = ["0.0.0.0/0"]
  }
  expect_failures = [var.endpoint_public_access_cidrs]
}

run "a_malformed_address_is_refused" {
  command = plan
  variables {
    endpoint_public_access_cidrs = ["not-an-address"]
  }
  expect_failures = [var.endpoint_public_access_cidrs]
}

run "kubernetes_secrets_are_encrypted_with_a_rotating_key" {
  command = plan

  assert {
    condition     = length(aws_kms_key.secrets) == 1 && aws_kms_key.secrets[0].enable_key_rotation
    error_message = "A dedicated key that rotates every year."
  }
  assert {
    condition     = aws_eks_cluster.this.encryption_config[0].resources == toset(["secrets"])
    error_message = "The cluster must encrypt its Secret objects."
  }
  assert {
    condition     = length(aws_iam_role_policy.cluster_kms) == 1
    error_message = "The cluster role needs permission to use that key."
  }
}

run "encryption_can_be_turned_off_for_a_throwaway_cluster" {
  command = plan
  variables {
    encrypt_secrets = false
  }

  assert {
    condition     = length(aws_kms_key.secrets) == 0 && length(aws_eks_cluster.this.encryption_config) == 0 && length(aws_iam_role_policy.cluster_kms) == 0
    error_message = "No key, no encryption config, no key permission."
  }
}

run "named_administrators_get_cluster_admin_and_nobody_else_does" {
  command = plan
  variables {
    admin_principal_arns = ["arn:aws:iam::123456789012:role/PlatformAdmins", "arn:aws:iam::123456789012:user/asha"]
  }

  assert {
    condition     = length(aws_eks_access_entry.admin) == 2 && length(aws_eks_access_policy_association.admin) == 2
    error_message = "One access entry and one policy association per administrator."
  }
  assert {
    condition     = alltrue([for a in aws_eks_access_policy_association.admin : endswith(a.policy_arn, "/AmazonEKSClusterAdminPolicy") && a.access_scope[0].type == "cluster"])
    error_message = "Administrators get the cluster-admin policy over the whole cluster."
  }
}

run "an_empty_administrator_list_is_refused" {
  command = plan
  variables {
    admin_principal_arns = []
  }
  expect_failures = [var.admin_principal_arns]
}

run "an_administrator_that_is_not_an_iam_arn_is_refused" {
  command = plan
  variables {
    admin_principal_arns = ["asha"]
  }
  expect_failures = [var.admin_principal_arns]
}

run "nodes_cannot_leak_their_credentials_to_pods_or_to_ssrf" {
  command = plan

  assert {
    condition     = aws_launch_template.node.metadata_options[0].http_tokens == "required"
    error_message = "IMDSv2 only."
  }
  assert {
    condition     = aws_launch_template.node.metadata_options[0].http_put_response_hop_limit == 1
    error_message = "Hop limit 1: pods cannot reach the node's instance metadata, so they cannot borrow the node's AWS permissions."
  }
}

run "node_disks_are_encrypted" {
  command = plan

  assert {
    condition     = aws_launch_template.node.block_device_mappings[0].ebs[0].encrypted == "true" # this field is a string in the AWS provider && aws_launch_template.node.block_device_mappings[0].ebs[0].volume_type == "gp3"
    error_message = "Encrypted gp3 root volumes."
  }
}

run "the_node_group_follows_the_scaling_inputs_on_private_subnets" {
  command = plan
  variables {
    node_min_size     = 2
    node_desired_size = 3
    node_max_size     = 6
  }

  assert {
    condition     = aws_eks_node_group.this.scaling_config[0].min_size == 2 && aws_eks_node_group.this.scaling_config[0].desired_size == 3 && aws_eks_node_group.this.scaling_config[0].max_size == 6
    error_message = "Scaling follows the inputs."
  }
  assert {
    condition     = aws_eks_node_group.this.subnet_ids == toset(["subnet-aaaa", "subnet-bbbb"]) && aws_eks_node_group.this.update_config[0].max_unavailable == 1
    error_message = "Nodes live in the private subnets and are replaced one at a time."
  }
  assert {
    condition     = aws_eks_node_group.this.ami_type == "AL2023_x86_64_STANDARD"
    error_message = "x86_64 nodes: the CI builds linux/amd64 images."
  }
}

run "nodes_get_exactly_the_four_standard_policies" {
  command = plan

  assert {
    condition     = toset([for a in aws_iam_role_policy_attachment.node : basename(a.policy_arn)]) == toset(["AmazonEKSWorkerNodePolicy", "AmazonEKS_CNI_Policy", "AmazonEC2ContainerRegistryReadOnly", "AmazonSSMManagedInstanceCore"])
    error_message = "Join the cluster, pod networking, pull images, and shell access through SSM."
  }
}

run "the_four_cluster_addons_are_installed" {
  command = plan

  assert {
    condition     = toset(keys(aws_eks_addon.this)) == toset(["vpc-cni", "kube-proxy", "coredns", "eks-pod-identity-agent"])
    error_message = "Pod networking, service proxy, DNS, and the Pod Identity agent."
  }
}

run "network_policies_are_actually_enforced" {
  command = plan

  assert {
    condition     = jsondecode(aws_eks_addon.this["vpc-cni"].configuration_values).enableNetworkPolicy == "true"
    error_message = "Without this the Kubernetes NetworkPolicies are accepted but ignored."
  }
}

run "service_accounts_are_connected_to_their_iam_roles" {
  command = plan
  variables {
    pod_identity_associations = {
      fee  = { namespace = "school-test", service_account = "fee", role_arn = "arn:aws:iam::123456789012:role/school-test-fee" }
      auth = { namespace = "school-test", service_account = "auth", role_arn = "arn:aws:iam::123456789012:role/school-test-auth" }
    }
  }

  assert {
    condition     = toset(keys(aws_eks_pod_identity_association.this)) == toset(["fee", "auth"]) && aws_eks_pod_identity_association.this["fee"].service_account == "fee"
    error_message = "One association per service account."
  }
}

run "the_load_balancer_controller_has_its_own_role_in_kube_system" {
  command = plan

  assert {
    condition     = aws_eks_pod_identity_association.load_balancer_controller.namespace == "kube-system" && aws_eks_pod_identity_association.load_balancer_controller.service_account == "aws-load-balancer-controller"
    error_message = "The Helm chart in Phase 15 must use exactly this namespace and service account name."
  }
}

run "the_vendored_load_balancer_policy_is_real_and_not_empty" {
  command = plan

  assert {
    condition     = length(jsondecode(aws_iam_role_policy.load_balancer_controller.policy).Statement) >= 10
    error_message = "The official policy has many statements; an empty or truncated file must fail here."
  }
  assert {
    condition     = contains(flatten([for s in jsondecode(aws_iam_role_policy.load_balancer_controller.policy).Statement : s.Action]), "elasticloadbalancing:CreateLoadBalancer")
    error_message = "The controller must be allowed to create load balancers."
  }
}

run "only_the_eks_service_can_assume_the_cluster_role_and_only_ec2_the_node_role" {
  command = plan

  assert {
    condition     = jsondecode(aws_iam_role.cluster.assume_role_policy).Statement[0].Principal.Service == "eks.amazonaws.com"
    error_message = "Cluster role: EKS only."
  }
  assert {
    condition     = jsondecode(aws_iam_role.node.assume_role_policy).Statement[0].Principal.Service == "ec2.amazonaws.com"
    error_message = "Node role: EC2 only."
  }
  assert {
    condition     = jsondecode(aws_iam_role.load_balancer_controller.assume_role_policy).Statement[0].Principal.Service == "pods.eks.amazonaws.com"
    error_message = "Controller role: Pod Identity only."
  }
}

run "a_single_subnet_is_refused" {
  command = plan
  variables {
    subnet_ids = ["subnet-aaaa"]
  }
  expect_failures = [var.subnet_ids]
}

run "a_malformed_kubernetes_version_is_refused" {
  command = plan
  variables {
    kubernetes_version = "latest"
  }
  expect_failures = [var.kubernetes_version]
}
