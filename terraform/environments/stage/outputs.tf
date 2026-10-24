output "vpc_id" {
  description = "Id of the VPC."
  value       = module.vpc.vpc_id
}

output "azs" {
  description = "Availability zones in use."
  value       = module.vpc.azs
}

output "public_subnet_ids" {
  description = "Public subnets (load balancers, NAT)."
  value       = module.vpc.public_subnet_ids
}

output "private_subnet_ids" {
  description = "Private subnets (Kubernetes nodes and pods)."
  value       = module.vpc.private_subnet_ids
}

output "database_subnet_ids" {
  description = "Database subnets (RDS)."
  value       = module.vpc.database_subnet_ids
}

output "nat_public_ips" {
  description = "Addresses the platform uses for outbound internet traffic."
  value       = module.vpc.nat_public_ips
}

output "ecr_repository_urls" {
  description = "Image repositories (empty in environments that do not own the registry)."
  value       = one(module.ecr[*].repository_urls)
}

# ---- what Phases 14-15 (EKS, Helm) and the deploy pipeline need ----------------------------------------------------------------
output "rds_address" {
  description = "Database host name (the DB_HOST setting)."
  value       = module.rds.address
}

output "rds_security_group_id" {
  description = "Database security group; the EKS module adds the rule that lets the nodes connect."
  value       = module.rds.security_group_id
}

output "rds_master_secret_arn" {
  description = "Secrets Manager secret with the database administrator login (used by the bootstrap job)."
  value       = module.rds.master_user_secret_arn
}

output "db_secret_arns" {
  description = "Per-service database login secrets, keyed <service>_app / <service>_migrator."
  value       = module.secrets.db_secret_arns
}

output "jwt_private_secret_arn" {
  description = "Where scripts/aws/put-jwt-key.sh stores the token signing key."
  value       = module.secrets.jwt_private_secret_arn
}

output "jwt_public_secret_arn" {
  description = "Where the token verification key is stored."
  value       = module.secrets.jwt_public_secret_arn
}

output "events_queue_url" {
  description = "The SQS_QUEUE_URL setting."
  value       = module.events.queue_url
}

output "events_dlq_url" {
  description = "Dead-letter queue (inspect it when the DLQ alarm fires)."
  value       = module.events.dlq_url
}

output "notifications_topic_arn" {
  description = "The SNS_TOPIC_ARN setting."
  value       = module.notifications_topic.topic_arn
}

output "alerts_topic_arn" {
  description = "Alarms are published here."
  value       = module.alerts_topic.topic_arn
}

output "pod_role_arns" {
  description = "IAM role per service, to be associated with its Kubernetes service account (Phase 14)."
  value       = module.pod_roles.role_arns
}

output "frontend_bucket" {
  description = "Upload the built frontend here (aws s3 sync)."
  value       = module.frontend_bucket.bucket_id
}

output "cloudfront_distribution_id" {
  description = "Invalidate this after each frontend deploy."
  value       = module.cdn.distribution_id
}

output "portal_domain_name" {
  description = "The portal's *.cloudfront.net address."
  value       = module.cdn.domain_name
}

output "alarm_names" {
  description = "Every CloudWatch alarm that was created."
  value       = module.observability.alarm_names
}

output "eks_cluster_name" {
  description = "Cluster name."
  value       = module.eks.cluster_name
}

output "kubeconfig_command" {
  description = "Run this to point kubectl at the cluster."
  value       = "aws eks update-kubeconfig --name ${module.eks.cluster_name} --region ${var.aws_region}"
}

output "kubernetes_namespace" {
  description = "The namespace the Helm charts must deploy into."
  value       = local.kubernetes_namespace
}

output "load_balancer_controller_role_arn" {
  description = "Role the AWS Load Balancer Controller uses (service account aws-load-balancer-controller in kube-system)."
  value       = module.eks.load_balancer_controller_role_arn
}

# ---- the inputs scripts/helm/render-env-values.py turns into Helm values ------------------------------------------------------------
output "environment" {
  description = "dev, stage or prod."
  value       = var.environment
}

output "aws_region" {
  description = "Region of this environment."
  value       = var.aws_region
}

output "vpc_cidr_block" {
  description = "Address range of the VPC (used by the Kubernetes network policies)."
  value       = module.vpc.vpc_cidr_block
}

output "image_registry" {
  description = "Host name of the ECR registry the pods pull from."
  value       = local.image_registry
}

output "alb_security_group_id" {
  description = "Security group the Ingress puts on the load balancer (accepts only CloudFront)."
  value       = aws_security_group.alb.id
}

output "github_ecr_push_role_arn" {
  description = "Store as the GitHub repository variable AWS_ECR_PUSH_ROLE_ARN (null where this environment does not own the registry)."
  value       = module.github_oidc.role_arn
}

output "github_frontend_deploy_role_arn" {
  description = "Store in the GitHub Environment frontend-<env> as the variable AWS_FRONTEND_DEPLOY_ROLE_ARN."
  value       = module.github_oidc.frontend_deploy_role_arn
}
