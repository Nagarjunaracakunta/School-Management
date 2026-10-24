output "role_arn" {
  description = "Store this in GitHub as the repository variable AWS_ECR_PUSH_ROLE_ARN (an address, not a secret). null where this account has no registry."
  value       = one(aws_iam_role.ecr_push[*].arn)
}

output "subject" {
  description = "The token subject the role trusts. If a push is refused, compare this with the token's actual subject."
  value       = local.subject
}

output "frontend_deploy_role_arn" {
  description = "Store this in the GitHub Environment (frontend-<env>) as the variable AWS_FRONTEND_DEPLOY_ROLE_ARN. null if no website bucket was given."
  value       = one(aws_iam_role.frontend_deploy[*].arn)
}

output "frontend_subject" {
  description = "The token subject the website-deploy role trusts."
  value       = local.frontend_subject
}
