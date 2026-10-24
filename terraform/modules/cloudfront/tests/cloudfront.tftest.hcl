mock_provider "aws" {
  mock_resource "aws_cloudfront_function" {
    defaults = {
      arn = "arn:aws:cloudfront::123456789012:function/school-test-spa-routing"
    }
  }
  mock_data "aws_iam_policy_document" {
    defaults = {
      json = "{\"Version\":\"2012-10-17\",\"Statement\":[]}"
    }
  }
}

variables {
  name                           = "school-test"
  s3_bucket_id                   = "school-test-frontend"
  s3_bucket_arn                  = "arn:aws:s3:::school-test-frontend"
  s3_bucket_regional_domain_name = "school-test-frontend.s3.ap-south-1.amazonaws.com"
}

run "frontend_only_until_the_api_load_balancer_exists" {
  command = plan

  assert {
    condition     = length(aws_cloudfront_distribution.this.origin) == 1 && length(aws_cloudfront_distribution.this.ordered_cache_behavior) == 0
    error_message = "Without api_origin_domain_name there is only the S3 origin and no /api behaviors."
  }
  assert {
    condition     = aws_cloudfront_distribution.this.default_root_object == "index.html"
    error_message = "The root URL serves index.html."
  }
}

run "static_files_are_cached_and_served_only_over_https" {
  command = apply

  assert {
    condition     = aws_cloudfront_distribution.this.default_cache_behavior[0].cache_policy_id == "658327ea-f89d-4fab-a63d-7e88639e58f6" && aws_cloudfront_distribution.this.default_cache_behavior[0].viewer_protocol_policy == "redirect-to-https"
    error_message = "Static files use the caching policy, and HTTP is redirected to HTTPS."
  }
  assert {
    condition     = aws_cloudfront_distribution.this.default_cache_behavior[0].compress
    error_message = "Compression should be on."
  }
}

run "the_api_is_routed_to_the_load_balancer_and_never_cached" {
  command = apply
  variables {
    api_origin_domain_name = "api-origin.school.example"
  }

  assert {
    condition     = length(aws_cloudfront_distribution.this.origin) == 2 && length(aws_cloudfront_distribution.this.ordered_cache_behavior) == 2
    error_message = "A second origin and two path behaviors (/api/* and /.well-known/*)."
  }
  assert {
    condition     = toset([for b in aws_cloudfront_distribution.this.ordered_cache_behavior : b.path_pattern]) == toset(["/api/*", "/.well-known/*"])
    error_message = "Only the API and the key-set paths go to the load balancer."
  }
  assert {
    condition     = alltrue([for b in aws_cloudfront_distribution.this.ordered_cache_behavior : b.cache_policy_id == "4135ea2d-6df8-44a3-9df3-4b5a84be39ad" && b.viewer_protocol_policy == "https-only"])
    error_message = "API responses are never cached and never served over plain HTTP."
  }
  assert {
    condition     = alltrue([for b in aws_cloudfront_distribution.this.ordered_cache_behavior : contains(b.allowed_methods, "POST") && contains(b.allowed_methods, "DELETE")])
    error_message = "The API needs every HTTP method."
  }
}

run "the_api_is_reached_over_encrypted_connections" {
  command = apply
  variables {
    api_origin_domain_name = "api-origin.school.example"
  }

  assert {
    condition     = one([for o in aws_cloudfront_distribution.this.origin : o if o.origin_id == "api-alb"]).custom_origin_config[0].origin_protocol_policy == "https-only"
    error_message = "CloudFront to the load balancer must be HTTPS."
  }
}

run "http_to_the_load_balancer_is_possible_only_when_asked_for" {
  command = apply
  variables {
    api_origin_domain_name = "k8s-school-0123.ap-south-1.elb.amazonaws.com"
    api_origin_protocol    = "http"
  }

  assert {
    condition     = one([for o in aws_cloudfront_distribution.this.origin : o if o.origin_id == "api-alb"]).custom_origin_config[0].origin_protocol_policy == "http-only"
    error_message = "api_origin_protocol = http selects http-only."
  }
  assert {
    condition     = alltrue([for b in aws_cloudfront_distribution.this.ordered_cache_behavior : b.viewer_protocol_policy == "https-only"])
    error_message = "Viewers always use HTTPS, whatever the origin protocol."
  }
}

run "an_unknown_origin_protocol_is_rejected" {
  command = plan
  variables {
    api_origin_protocol = "ftp"
  }
  expect_failures = [var.api_origin_protocol]
}

run "single_page_app_routing_never_rewrites_api_answers" {
  command = apply
  variables {
    api_origin_domain_name = "api-origin.school.example"
  }

  # REGRESSION GUARD. Distribution-wide custom error responses would turn an API 404 into index.html with status 200.
  assert {
    condition     = length(aws_cloudfront_distribution.this.custom_error_response) == 0
    error_message = "Do not use custom error responses: they apply to API responses too. Use the routing function."
  }
  assert {
    condition     = length(aws_cloudfront_distribution.this.default_cache_behavior[0].function_association) == 1 && alltrue([for b in aws_cloudfront_distribution.this.ordered_cache_behavior : length(b.function_association) == 0])
    error_message = "The routing function belongs to the static-file behavior only."
  }
  assert {
    condition     = aws_cloudfront_function.spa_routing.runtime == "cloudfront-js-2.0" && strcontains(aws_cloudfront_function.spa_routing.code, "/index.html")
    error_message = "The function rewrites app routes to /index.html."
  }
}

run "security_headers_are_set_on_every_response" {
  command = plan

  assert {
    condition     = aws_cloudfront_response_headers_policy.security.security_headers_config[0].strict_transport_security[0].access_control_max_age_sec >= 31536000
    error_message = "HSTS for at least a year."
  }
  assert {
    condition     = aws_cloudfront_response_headers_policy.security.security_headers_config[0].frame_options[0].frame_option == "DENY" && aws_cloudfront_response_headers_policy.security.security_headers_config[0].content_type_options[0].override
    error_message = "No framing, and nosniff."
  }
  assert {
    condition     = strcontains(aws_cloudfront_response_headers_policy.security.security_headers_config[0].content_security_policy[0].content_security_policy, "default-src 'self'")
    error_message = "A Content-Security-Policy that defaults to the same origin."
  }
}

run "the_default_certificate_is_used_until_a_domain_is_configured" {
  command = plan

  assert {
    condition     = aws_cloudfront_distribution.this.viewer_certificate[0].cloudfront_default_certificate == true
    error_message = "Without a certificate, use the *.cloudfront.net one."
  }
}

run "a_custom_domain_needs_a_certificate_and_modern_tls" {
  command = plan
  variables {
    aliases             = ["portal.school.example"]
    acm_certificate_arn = "arn:aws:acm:us-east-1:123456789012:certificate/11111111-2222-3333-4444-555555555555"
  }

  assert {
    condition     = aws_cloudfront_distribution.this.viewer_certificate[0].minimum_protocol_version == "TLSv1.2_2021" && aws_cloudfront_distribution.this.viewer_certificate[0].ssl_support_method == "sni-only"
    error_message = "A custom certificate allows (and we require) TLS 1.2 or newer."
  }
}

run "domain_names_without_a_certificate_are_rejected" {
  command = plan
  variables {
    aliases = ["portal.school.example"]
  }
  expect_failures = [var.aliases]
}

run "a_certificate_outside_us_east_1_is_rejected" {
  command = plan
  variables {
    acm_certificate_arn = "arn:aws:acm:ap-south-1:123456789012:certificate/11111111-2222-3333-4444-555555555555"
  }
  expect_failures = [var.acm_certificate_arn]
}

run "only_cloudfront_may_read_the_bucket" {
  command = plan

  assert {
    condition     = aws_s3_bucket_policy.frontend.bucket == "school-test-frontend"
    error_message = "The access policy is attached to the frontend bucket."
  }
  assert {
    condition     = aws_cloudfront_origin_access_control.s3.signing_behavior == "always" && aws_cloudfront_origin_access_control.s3.origin_access_control_origin_type == "s3"
    error_message = "CloudFront must always sign its requests to S3."
  }
}
