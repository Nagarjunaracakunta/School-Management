terraform {
  # LOCAL state, on purpose (see main.tf). The path is given at init time, one file per AWS account, so bootstrapping
  # stage can never see or modify dev's state:
  #   terraform init -backend-config="path=state/dev.tfstate"        (scripts/tf/bootstrap.sh does this for you)
  backend "local" {}
}
