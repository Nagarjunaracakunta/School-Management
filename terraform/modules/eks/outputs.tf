output "cluster_name" {
  description = "Cluster name (aws eks update-kubeconfig --name <this>)."
  value       = aws_eks_cluster.this.name
}

output "cluster_endpoint" {
  description = "The Kubernetes API address."
  value       = aws_eks_cluster.this.endpoint
}

output "cluster_security_group_id" {
  description = "Security group of the cluster and its nodes. Other resources (the database) allow traffic FROM this group."
  value       = aws_eks_cluster.this.vpc_config[0].cluster_security_group_id
}

output "node_role_arn" {
  description = "IAM role of the worker nodes."
  value       = aws_iam_role.node.arn
}

output "load_balancer_controller_role_arn" {
  description = "IAM role the AWS Load Balancer Controller assumes."
  value       = aws_iam_role.load_balancer_controller.arn
}

output "secrets_kms_key_arn" {
  description = "KMS key that encrypts Kubernetes Secrets (null when encrypt_secrets is false)."
  value       = one(aws_kms_key.secrets[*].arn)
}
