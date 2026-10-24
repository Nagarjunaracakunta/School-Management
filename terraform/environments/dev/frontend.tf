data "aws_caller_identity" "current" {}

# ---- the built React app lives in a private bucket; only CloudFront can read it (decision D1) --------------------------
module "frontend_bucket" {
  source = "../../modules/s3"

  # The account id makes the name globally unique and shows whose bucket it is.
  name          = "${local.name_prefix}-frontend-${data.aws_caller_identity.current.account_id}"
  force_destroy = var.frontend_force_destroy
}

module "cdn" {
  source = "../../modules/cloudfront"

  name                           = local.name_prefix
  s3_bucket_id                   = module.frontend_bucket.bucket_id
  s3_bucket_arn                  = module.frontend_bucket.bucket_arn
  s3_bucket_regional_domain_name = module.frontend_bucket.bucket_regional_domain_name
  api_origin_domain_name         = var.api_origin_domain_name
  api_origin_protocol            = var.api_origin_protocol
  aliases                        = var.domain_aliases
  acm_certificate_arn            = var.acm_certificate_arn
  price_class                    = var.cloudfront_price_class
}
