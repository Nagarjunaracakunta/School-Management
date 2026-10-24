mock_provider "aws" {}

variables {
  name           = "school-test-db"
  vpc_id         = "vpc-0123456789abcdef0"
  subnet_ids     = ["subnet-aaaa", "subnet-bbbb"]
  instance_class = "db.t4g.micro"
}

run "the_administrator_password_is_managed_by_rds_and_never_seen_by_terraform" {
  command = plan

  assert {
    condition     = aws_db_instance.this.manage_master_user_password == true
    error_message = "RDS must manage the master password (so it never enters Terraform state)."
  }
  assert {
    condition     = aws_db_instance.this.password == null && aws_db_instance.this.password_wo == null
    error_message = "No password may be set in Terraform."
  }
}

run "the_database_is_private_and_encrypted" {
  command = plan

  assert {
    condition     = aws_db_instance.this.publicly_accessible == false && aws_db_instance.this.storage_encrypted == true
    error_message = "Never public, always encrypted."
  }
  assert {
    condition     = aws_db_instance.this.engine == "postgres" && aws_db_instance.this.storage_type == "gp3"
    error_message = "PostgreSQL on gp3 storage."
  }
}

run "only_encrypted_connections_are_accepted" {
  command = plan

  assert {
    condition     = contains([for p in aws_db_parameter_group.this.parameter : p.name], "rds.force_ssl") && aws_db_parameter_group.this.family == "postgres16"
    error_message = "rds.force_ssl must be switched on in the parameter group."
  }
}

run "the_firewall_starts_closed" {
  command = apply

  assert {
    condition     = length(aws_security_group.this.ingress) == 0
    error_message = "The database security group must have no ingress rules of its own: the caller opens exactly what it needs."
  }
}

run "dev_defaults_are_cheap_and_disposable" {
  command = plan

  assert {
    condition     = aws_db_instance.this.multi_az == false && aws_db_instance.this.deletion_protection == false && aws_db_instance.this.skip_final_snapshot == true
    error_message = "Defaults suit a throwaway dev database."
  }
  assert {
    condition     = aws_db_instance.this.final_snapshot_identifier == null && aws_db_instance.this.performance_insights_enabled == false
    error_message = "No final snapshot name when skipping it; no Performance Insights by default."
  }
}

run "production_settings" {
  command = plan
  variables {
    multi_az              = true
    deletion_protection   = true
    skip_final_snapshot   = false
    performance_insights  = true
    backup_retention_days = 14
    instance_class        = "db.t4g.medium"
  }

  assert {
    condition     = aws_db_instance.this.multi_az && aws_db_instance.this.deletion_protection && aws_db_instance.this.backup_retention_period == 14
    error_message = "Multi-AZ, deletion protection and 14 days of backups."
  }
  assert {
    condition     = aws_db_instance.this.final_snapshot_identifier == "school-test-db-final" && aws_db_instance.this.performance_insights_retention_period == 7
    error_message = "A named final snapshot and 7 days of Performance Insights."
  }
}

run "database_logs_have_a_retention_period" {
  command = plan
  variables {
    log_retention_days = 14
  }

  assert {
    condition     = aws_cloudwatch_log_group.postgresql.name == "/aws/rds/instance/school-test-db/postgresql" && aws_cloudwatch_log_group.postgresql.retention_in_days == 14
    error_message = "We create the log group so logs are not kept forever."
  }
}

run "rejects_a_single_subnet" {
  command = plan
  variables {
    subnet_ids = ["subnet-aaaa"]
  }
  expect_failures = [var.subnet_ids]
}

run "rejects_too_long_a_backup_window" {
  command = plan
  variables {
    backup_retention_days = 90
  }
  expect_failures = [var.backup_retention_days]
}
