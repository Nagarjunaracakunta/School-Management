# ---- the database (one PostgreSQL instance, one schema per service: ADR D5) --------------------------------------------
module "rds" {
  source = "../../modules/rds"

  name                     = "${local.name_prefix}-db"
  vpc_id                   = module.vpc.vpc_id
  subnet_ids               = module.vpc.database_subnet_ids
  instance_class           = var.rds_instance_class
  allocated_storage_gb     = var.rds_allocated_storage_gb
  max_allocated_storage_gb = var.rds_max_allocated_storage_gb
  multi_az                 = var.rds_multi_az
  backup_retention_days    = var.rds_backup_retention_days
  deletion_protection      = var.rds_deletion_protection
  skip_final_snapshot      = var.rds_skip_final_snapshot
  performance_insights     = var.rds_performance_insights

  depends_on = [terraform_data.guardrails]
}

# ---- logins for every service, and the token signing-key containers ----------------------------------------------------
module "secrets" {
  source = "../../modules/secrets"

  name_prefix          = local.secret_prefix
  services             = toset(local.services)
  db_host              = module.rds.address
  db_port              = module.rds.port
  db_name              = module.rds.db_name
  recovery_window_days = var.secrets_recovery_days
}
