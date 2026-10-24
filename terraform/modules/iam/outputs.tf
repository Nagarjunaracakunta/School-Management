output "role_arns" {
  description = "Role ARN per service (the EKS module associates each with its Kubernetes service account)."
  value       = { for k, r in aws_iam_role.this : k => r.arn }
}

output "role_names" {
  description = "Role name per service."
  value       = { for k, r in aws_iam_role.this : k => r.name }
}
