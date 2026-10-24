variable "name" {
  description = "Name prefix, for example school-dev."
  type        = string
}

variable "s3_bucket_id" {
  description = "Bucket holding the built frontend."
  type        = string
}

variable "s3_bucket_arn" {
  description = "ARN of that bucket (the bucket policy that lets CloudFront in is attached here)."
  type        = string
}

variable "s3_bucket_regional_domain_name" {
  description = "Regional domain name of that bucket."
  type        = string
}

variable "api_origin_protocol" {
  description = <<-EOT
    https (default): CloudFront talks to the load balancer over TLS; the load balancer needs a certificate whose name matches
    api_origin_domain_name. http: for a learning environment WITHOUT your own domain only. The hop from CloudFront to the load
    balancer is then unencrypted (the viewer's connection to CloudFront is still HTTPS, and the load balancer still accepts
    only CloudFront). The environment's guardrails refuse it outside dev.
  EOT
  type        = string
  default     = "https"

  validation {
    condition     = contains(["https", "http"], var.api_origin_protocol)
    error_message = "api_origin_protocol must be https or http."
  }
}

variable "api_origin_domain_name" {
  description = <<-EOT
    Host name of the load balancer that serves /api/*. It only exists after the Kubernetes Ingress has created the ALB
    (Phase 14/15), so it is optional: leave it null and the distribution serves just the frontend, then set it and apply
    again. Use a name that has a certificate on the ALB (for example api-origin.school.example), because CloudFront
    talks to it over HTTPS.
  EOT
  type        = string
  default     = null
}

variable "aliases" {
  description = "Your own domain names for the site, for example [\"portal.school.example\"]. Needs acm_certificate_arn."
  type        = list(string)
  default     = []

  validation {
    condition     = length(var.aliases) == 0 || var.acm_certificate_arn != null
    error_message = "aliases were given without an acm_certificate_arn: the site would be unreachable by those names."
  }
}

variable "acm_certificate_arn" {
  description = "ACM certificate for the aliases. It MUST be in us-east-1 (a CloudFront rule), whatever region the rest is in."
  type        = string
  default     = null

  validation {
    condition     = var.acm_certificate_arn == null || can(regex("^arn:aws:acm:us-east-1:", var.acm_certificate_arn))
    error_message = "acm_certificate_arn must be a certificate in us-east-1."
  }
}

variable "web_acl_arn" {
  description = "WAF web ACL to attach (must be a CLOUDFRONT-scope ACL in us-east-1). null = none."
  type        = string
  default     = null
}

variable "price_class" {
  description = "Which edge locations to use. PriceClass_200 covers Asia, Europe and North America at lower cost than PriceClass_All."
  type        = string
  default     = "PriceClass_200"

  validation {
    condition     = contains(["PriceClass_100", "PriceClass_200", "PriceClass_All"], var.price_class)
    error_message = "price_class must be PriceClass_100, PriceClass_200 or PriceClass_All."
  }
}

variable "content_security_policy" {
  description = "Browser rule about where scripts, styles and API calls may come from. Same policy as the local nginx container."
  type        = string
  default     = "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'self'; form-action 'self'"
}

variable "tags" {
  description = "Extra tags."
  type        = map(string)
  default     = {}
}
