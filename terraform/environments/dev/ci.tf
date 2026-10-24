# ---- how the pipelines (GitHub Actions) are allowed into AWS -------------------------------------------------------------------
# GitHub proves its identity with a short-lived OIDC token, so no access key exists anywhere. Every account needs the identity
# provider and the website-deploy role; only the account that owns the registry (dev) also gets the image-push role.
module "github_oidc" {
  source = "../../modules/github-oidc"

  name_prefix       = local.name_prefix
  github_repository = var.github_repository
  create_provider   = var.github_create_oidc_provider

  # images are built once, in dev, and the other environments pull them
  ecr_repository_arns = var.manage_ecr ? values(module.ecr[0].repository_arns) : []

  # the website of THIS environment
  create_frontend_deploy_role = true
  frontend_github_environment = "frontend-${var.environment}"
  frontend_bucket_arn         = module.frontend_bucket.bucket_arn
  frontend_distribution_arn   = module.cdn.distribution_arn
}
