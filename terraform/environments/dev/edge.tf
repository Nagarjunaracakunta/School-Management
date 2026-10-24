# ---- the load balancer's firewall ---------------------------------------------------------------------------------------------
# The Application Load Balancer itself is created by the AWS Load Balancer Controller from the Kubernetes Ingress objects
# (Phase 15). Its security group is created HERE, because it is part of the platform's security design: the load balancer
# accepts connections from CloudFront and from nothing else.
data "aws_ec2_managed_prefix_list" "cloudfront" {
  name = "com.amazonaws.global.cloudfront.origin-facing" # AWS keeps this list of CloudFront's addresses up to date for us
}

resource "aws_security_group" "alb" {
  name        = "${local.name_prefix}-alb"
  description = "Public load balancer: only CloudFront may connect"
  vpc_id      = module.vpc.vpc_id

  tags = { Name = "${local.name_prefix}-alb" }

  lifecycle {
    create_before_destroy = true
  }
}

# One port only: 443 when the load balancer has a certificate, 80 in the certificate-less dev trial (api_origin_protocol = http). A rule that refers to this prefix list is counted as ~55 rules against AWS's limit of 60 per security
# group, so a second port would need a quota increase.
resource "aws_vpc_security_group_ingress_rule" "alb_from_cloudfront" {
  security_group_id = aws_security_group.alb.id
  prefix_list_id    = data.aws_ec2_managed_prefix_list.cloudfront.id
  ip_protocol       = "tcp"
  from_port         = var.api_origin_protocol == "https" ? 443 : 80
  to_port           = var.api_origin_protocol == "https" ? 443 : 80
  description       = var.api_origin_protocol == "https" ? "HTTPS from CloudFront only" : "HTTP from CloudFront only (dev trial without a domain)"
}

resource "aws_vpc_security_group_egress_rule" "alb_to_pods" {
  security_group_id = aws_security_group.alb.id
  cidr_ipv4         = module.vpc.vpc_cidr_block
  ip_protocol       = "tcp"
  from_port         = 8000
  to_port           = 8000
  description       = "To the service pods (port 8000) inside the VPC"
}

locals {
  # Where the images live: this account's registry, or the owner's (dev) when this environment does not own one.
  registry_account_id = var.manage_ecr ? module.ecr[0].registry_id : var.ecr_owner_account_id
  image_registry      = "${local.registry_account_id}.dkr.ecr.${var.aws_region}.amazonaws.com"
}
