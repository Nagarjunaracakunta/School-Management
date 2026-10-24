terraform {
  required_version = ">= 1.11, < 2.0" # write-only secrets and ephemeral resources (database passwords stay out of the state) need 1.11

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 6.0"
    }
  }
}
