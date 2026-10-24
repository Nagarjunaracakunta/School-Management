provider "aws" {
  region = var.aws_region

  # Safety net: Terraform refuses to run if the credentials belong to any other account. Without it, applying the
  # dev configuration while logged in to the prod account would quietly build dev resources in prod.
  allowed_account_ids = var.allowed_account_ids

  # Stamped on every resource that supports tags, so the bill and the console can be filtered by project/environment.
  default_tags {
    tags = {
      Project     = var.project
      Environment = var.environment
      ManagedBy   = "terraform"
      Owner       = var.owner
      Repository  = "school-management"
    }
  }
}
