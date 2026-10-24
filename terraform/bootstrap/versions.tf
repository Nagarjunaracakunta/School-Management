terraform {
  required_version = ">= 1.10, < 2.0" # 1.10 added the S3 backend's native lock file (no DynamoDB table needed)

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 6.0"
    }
  }
}
