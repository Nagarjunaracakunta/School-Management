output "db_secret_arns" {
  description = "ARN of each database login secret, keyed <service>_app or <service>_migrator."
  value       = { for k, s in aws_secretsmanager_secret.db : k => s.arn }
}

output "jwt_private_secret_arn" {
  description = "ARN of the signing-key secret (only the Auth service may read it)."
  value       = aws_secretsmanager_secret.jwt_private.arn
}

output "jwt_public_secret_arn" {
  description = "ARN of the verification-key secret (every service reads it)."
  value       = aws_secretsmanager_secret.jwt_public.arn
}
