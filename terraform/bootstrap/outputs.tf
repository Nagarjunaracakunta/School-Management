output "state_bucket" {
  description = "Name of the bucket that holds this account's Terraform state."
  value       = aws_s3_bucket.state.id
}

output "backend_hcl" {
  description = "Paste this into terraform/environments/<env>/backend.hcl, then run: terraform init -backend-config=backend.hcl"
  value       = <<-EOT
    bucket = "${aws_s3_bucket.state.id}"
    region = "${var.aws_region}"
  EOT
}
