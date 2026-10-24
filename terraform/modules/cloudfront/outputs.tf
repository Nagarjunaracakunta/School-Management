output "distribution_id" {
  description = "Distribution id (used to invalidate the cache after a deploy)."
  value       = aws_cloudfront_distribution.this.id
}

output "distribution_arn" {
  description = "Distribution ARN."
  value       = aws_cloudfront_distribution.this.arn
}

output "domain_name" {
  description = "The *.cloudfront.net address of the portal."
  value       = aws_cloudfront_distribution.this.domain_name
}
