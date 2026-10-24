locals {
  s3_origin_id   = "frontend-s3"
  api_origin_id  = "api-alb"
  has_api        = var.api_origin_domain_name != null
  api_path_rules = local.has_api ? ["/api/*", "/.well-known/*"] : []
}

# AWS-managed policies. Their ids are fixed, published constants (the same in every account), so we name them here
# instead of looking them up: fewer API calls, and the wiring below can be tested exactly.
#   https://docs.aws.amazon.com/AmazonCloudFront/latest/DeveloperGuide/using-managed-cache-policies.html
locals {
  cache_policy_optimized         = "658327ea-f89d-4fab-a63d-7e88639e58f6" # Managed-CachingOptimized: cache static files, honours our Cache-Control
  cache_policy_disabled          = "4135ea2d-6df8-44a3-9df3-4b5a84be39ad" # Managed-CachingDisabled: never cache (API responses)
  origin_request_all_except_host = "b689b0a8-53d0-40ab-baf2-68738e2966ac" # Managed-AllViewerExceptHostHeader: forward Authorization, X-Request-ID, cookies, query strings
}

# ---- origin access control: how CloudFront proves who it is to S3 ----------------------------------------------------------
resource "aws_cloudfront_origin_access_control" "s3" {
  name                              = "${var.name}-frontend"
  description                       = "CloudFront signs its requests to the frontend bucket"
  origin_access_control_origin_type = "s3"
  signing_behavior                  = "always"
  signing_protocol                  = "sigv4"
}

# ---- security headers, set on every response (the nginx container does the same locally) ----------------------------------
resource "aws_cloudfront_response_headers_policy" "security" {
  name = "${var.name}-security-headers"

  security_headers_config {
    strict_transport_security {
      access_control_max_age_sec = 63072000 # two years: browsers remember to use HTTPS only
      include_subdomains         = true
      preload                    = false
      override                   = true
    }
    content_type_options {
      override = true # nosniff
    }
    frame_options {
      frame_option = "DENY"
      override     = true
    }
    referrer_policy {
      referrer_policy = "no-referrer"
      override        = true
    }
    content_security_policy {
      content_security_policy = var.content_security_policy
      override                = true
    }
  }
}

# ---- single-page-app routing ---------------------------------------------------------------------------------------------
# /payments is not a file in S3; it is a page of the React app. Requests for paths without a file extension are rewritten
# to /index.html and React Router takes over.
#
# Why a function, not "custom error responses" (the usual tutorial answer)? Custom error responses apply to the WHOLE
# distribution. A real API answer such as 404 "Student not found" would be replaced by index.html with status 200,
# and the API would appear to lie. The function is attached to the static-file behavior only.
resource "aws_cloudfront_function" "spa_routing" {
  name    = "${var.name}-spa-routing"
  runtime = "cloudfront-js-2.0"
  comment = "Rewrite extension-less paths to /index.html"
  publish = true

  code = <<-JS
    function handler(event) {
      var request = event.request;
      var uri = request.uri;
      // "/assets/app.3f9c.js" has a dot (a real file): leave it alone. "/payments" has none: it is an app route.
      if (uri.indexOf('.') === -1) {
        request.uri = '/index.html';
      }
      return request;
    }
  JS
}

# ---- the distribution ------------------------------------------------------------------------------------------------------
resource "aws_cloudfront_distribution" "this" {
  enabled             = true
  comment             = "${var.name} portal"
  default_root_object = "index.html"
  price_class         = var.price_class
  http_version        = "http2and3"
  is_ipv6_enabled     = true
  aliases             = var.aliases
  web_acl_id          = var.web_acl_arn

  origin {
    origin_id                = local.s3_origin_id
    domain_name              = var.s3_bucket_regional_domain_name
    origin_access_control_id = aws_cloudfront_origin_access_control.s3.id
  }

  dynamic "origin" {
    for_each = local.has_api ? [1] : []

    content {
      origin_id   = local.api_origin_id
      domain_name = var.api_origin_domain_name

      custom_origin_config {
        http_port              = 80
        https_port             = 443
        origin_protocol_policy = var.api_origin_protocol == "https" ? "https-only" : "http-only" # https: CloudFront to the load balancer is encrypted too
        origin_ssl_protocols   = ["TLSv1.2"]
      }
    }
  }

  # Default: the static frontend
  default_cache_behavior {
    target_origin_id           = local.s3_origin_id
    viewer_protocol_policy     = "redirect-to-https"
    allowed_methods            = ["GET", "HEAD", "OPTIONS"]
    cached_methods             = ["GET", "HEAD"]
    compress                   = true
    cache_policy_id            = local.cache_policy_optimized
    response_headers_policy_id = aws_cloudfront_response_headers_policy.security.id

    function_association {
      event_type   = "viewer-request"
      function_arn = aws_cloudfront_function.spa_routing.arn
    }
  }

  # /api/* and /.well-known/*: straight through to the load balancer, never cached, never rewritten
  dynamic "ordered_cache_behavior" {
    for_each = local.api_path_rules

    content {
      path_pattern               = ordered_cache_behavior.value
      target_origin_id           = local.api_origin_id
      viewer_protocol_policy     = "https-only"
      allowed_methods            = ["GET", "HEAD", "OPTIONS", "PUT", "POST", "PATCH", "DELETE"]
      cached_methods             = ["GET", "HEAD"]
      compress                   = true
      cache_policy_id            = local.cache_policy_disabled
      origin_request_policy_id   = local.origin_request_all_except_host
      response_headers_policy_id = aws_cloudfront_response_headers_policy.security.id
    }
  }

  restrictions {
    geo_restriction {
      restriction_type = "none"
    }
  }

  viewer_certificate {
    cloudfront_default_certificate = var.acm_certificate_arn == null
    acm_certificate_arn            = var.acm_certificate_arn
    ssl_support_method             = var.acm_certificate_arn == null ? null : "sni-only"
    minimum_protocol_version       = var.acm_certificate_arn == null ? "TLSv1" : "TLSv1.2_2021"
  }

  tags = merge(var.tags, { Name = "${var.name}-portal" })
}

# ---- let CloudFront (and only this distribution) read the bucket ------------------------------------------------------------
data "aws_iam_policy_document" "bucket" {
  statement {
    sid       = "AllowThisDistributionToReadFiles"
    actions   = ["s3:GetObject"]
    resources = ["${var.s3_bucket_arn}/*"]

    principals {
      type        = "Service"
      identifiers = ["cloudfront.amazonaws.com"]
    }

    condition {
      test     = "StringEquals"
      variable = "AWS:SourceArn"
      values   = [aws_cloudfront_distribution.this.arn]
    }
  }

  statement {
    sid       = "DenyInsecureTransport"
    effect    = "Deny"
    actions   = ["s3:*"]
    resources = [var.s3_bucket_arn, "${var.s3_bucket_arn}/*"]

    principals {
      type        = "*"
      identifiers = ["*"]
    }

    condition {
      test     = "Bool"
      variable = "aws:SecureTransport"
      values   = ["false"]
    }
  }
}

resource "aws_s3_bucket_policy" "frontend" {
  bucket = var.s3_bucket_id
  policy = data.aws_iam_policy_document.bucket.json
}
