output "repository_urls" {
  description = "Push/pull address of each repository, keyed by short name (for example auth)."
  value       = { for k, r in aws_ecr_repository.this : k => r.repository_url }
}

output "repository_arns" {
  description = "ARN of each repository, keyed by short name. Used to write least-privilege IAM policies."
  value       = { for k, r in aws_ecr_repository.this : k => r.arn }
}

output "registry_id" {
  description = "The AWS account id that owns the registry."
  value       = values(aws_ecr_repository.this)[0].registry_id # every repository in an account has the same registry id; the list is never empty (see the variable's validation)
}
