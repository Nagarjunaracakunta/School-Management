terraform {
  backend "s3" {
    # Where this environment's state lives. The state of each environment is a separate file, and (with separate AWS
    # accounts) a separate bucket, so a mistake in dev can never touch prod's record of what exists.
    #
    # The bucket is not named here because backend blocks cannot use variables: it is passed at init time from
    # backend.hcl:   terraform init -backend-config=backend.hcl
    key          = "school/stage/platform.tfstate"
    region       = "ap-south-1" # must be a literal: backend blocks cannot use variables
    encrypt      = true
    use_lockfile = true # a lock object next to the state file stops two people applying at once (Terraform 1.10+)
  }
}
