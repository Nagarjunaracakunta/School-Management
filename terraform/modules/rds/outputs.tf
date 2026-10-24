output "address" {
  description = "Host name the services connect to (the DB_HOST setting)."
  value       = aws_db_instance.this.address
}

output "port" {
  description = "Port (5432)."
  value       = aws_db_instance.this.port
}

output "db_name" {
  description = "Database name."
  value       = aws_db_instance.this.db_name
}

output "instance_id" {
  description = "Instance identifier (used by CloudWatch alarms)."
  value       = aws_db_instance.this.identifier
}

output "security_group_id" {
  description = "The database's security group. Add ingress rules to this, from the application's security group."
  value       = aws_security_group.this.id
}

output "master_user_secret_arn" {
  description = "Secrets Manager secret holding the administrator login (created and rotated by RDS)."
  value       = try(aws_db_instance.this.master_user_secret[0].secret_arn, null) # RDS creates the secret; null only before the instance exists
}
