resource "aws_db_subnet_group" "this" {
  name       = var.name
  subnet_ids = var.subnet_ids

  tags = merge(var.tags, { Name = var.name })
}

# The database's firewall. It starts with NO rules: nothing can connect. The environment adds exactly one rule
# (from the Kubernetes nodes' security group) once the cluster exists. "Closed until opened" is the safe default.
resource "aws_security_group" "this" {
  name        = "${var.name}-db"
  description = "PostgreSQL for ${var.name}. Ingress rules are added by the caller."
  vpc_id      = var.vpc_id

  tags = merge(var.tags, { Name = "${var.name}-db" })

  lifecycle {
    create_before_destroy = true
  }
}

resource "aws_db_parameter_group" "this" {
  name_prefix = "${var.name}-"
  family      = "postgres${var.engine_version}"
  description = "Settings for ${var.name}"

  parameter {
    name  = "rds.force_ssl"
    value = "1" # the server refuses connections that are not encrypted
  }

  parameter {
    name  = "log_min_duration_statement"
    value = "500" # log any statement slower than 500 ms: the first thing to read when the app feels slow
  }

  tags = var.tags

  lifecycle {
    create_before_destroy = true
  }
}

# We create the log group ourselves. If RDS creates it, it never expires and quietly grows forever.
resource "aws_cloudwatch_log_group" "postgresql" {
  name              = "/aws/rds/instance/${var.name}/postgresql"
  retention_in_days = var.log_retention_days

  tags = var.tags
}

resource "aws_db_instance" "this" {
  identifier = var.name

  engine         = "postgres"
  engine_version = var.engine_version
  instance_class = var.instance_class

  db_name  = var.db_name
  username = var.master_username

  # RDS generates the administrator password, stores it in Secrets Manager and can rotate it. Terraform never sees it,
  # so it can never leak through the state file, a plan output or a log. (There is deliberately no `password` here.)
  manage_master_user_password = true

  storage_type          = "gp3"
  allocated_storage     = var.allocated_storage_gb
  max_allocated_storage = var.max_allocated_storage_gb
  storage_encrypted     = true
  kms_key_id            = var.kms_key_id

  db_subnet_group_name   = aws_db_subnet_group.this.name
  vpc_security_group_ids = [aws_security_group.this.id]
  parameter_group_name   = aws_db_parameter_group.this.name
  publicly_accessible    = false
  multi_az               = var.multi_az

  backup_retention_period = var.backup_retention_days
  backup_window           = "21:00-22:00"         # UTC, which is 02:30-03:30 in India: quiet hours
  maintenance_window      = "sun:22:30-sun:23:30" # UTC
  copy_tags_to_snapshot   = true

  deletion_protection       = var.deletion_protection
  skip_final_snapshot       = var.skip_final_snapshot
  final_snapshot_identifier = var.skip_final_snapshot ? null : "${var.name}-final"

  auto_minor_version_upgrade            = true
  performance_insights_enabled          = var.performance_insights
  performance_insights_retention_period = var.performance_insights ? 7 : null
  enabled_cloudwatch_logs_exports       = ["postgresql", "upgrade"]

  tags = merge(var.tags, { Name = var.name })

  lifecycle {
    # AWS applies minor upgrades by itself (16.4 -> 16.6). Without this, every such upgrade would show up as a
    # "difference" and Terraform would try to downgrade the database. Major upgrades are done on purpose, by hand.
    ignore_changes = [engine_version]
  }

  depends_on = [aws_cloudwatch_log_group.postgresql] # so our retention setting is in place before RDS starts logging
}
