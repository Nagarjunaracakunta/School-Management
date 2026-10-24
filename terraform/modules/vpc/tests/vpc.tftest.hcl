# Offline tests: the AWS provider is mocked, so these run in seconds with no account and no credentials.
mock_provider "aws" {
  mock_data "aws_region" {
    defaults = {
      region = "ap-south-1"
    }
  }
  mock_data "aws_iam_policy_document" {
    defaults = {
      json = "{\"Version\":\"2012-10-17\",\"Statement\":[]}"
    }
  }
}

variables {
  name       = "school-test"
  cidr_block = "10.10.0.0/16"
  azs        = ["ap-south-1a", "ap-south-1b"]
}

run "one_subnet_per_zone_per_tier" {
  command = plan

  assert {
    condition     = length(aws_subnet.public) == 2 && length(aws_subnet.private) == 2 && length(aws_subnet.database) == 2
    error_message = "Expected one public, one private and one database subnet per availability zone."
  }
}

run "address_plan_is_predictable_and_does_not_overlap" {
  command = plan
  variables {
    azs = ["ap-south-1a", "ap-south-1b", "ap-south-1c"]
  }

  assert {
    condition     = [for az in var.azs : aws_subnet.public[az].cidr_block] == ["10.10.0.0/24", "10.10.1.0/24", "10.10.2.0/24"]
    error_message = "Public subnets should be consecutive /24s at the start of the VPC range."
  }
  assert {
    condition     = [for az in var.azs : aws_subnet.private[az].cidr_block] == ["10.10.16.0/20", "10.10.32.0/20", "10.10.48.0/20"]
    error_message = "Private subnets should be /20s starting at 10.10.16.0."
  }
  assert {
    condition     = [for az in var.azs : aws_subnet.database[az].cidr_block] == ["10.10.200.0/24", "10.10.201.0/24", "10.10.202.0/24"]
    error_message = "Database subnets should be /24s starting at 10.10.200.0."
  }
}

run "default_is_one_shared_nat_gateway" {
  command = plan

  assert {
    condition     = length(aws_nat_gateway.this) == 1 && length(aws_eip.nat) == 1
    error_message = "nat_mode = single must create exactly one NAT gateway with one address."
  }
  assert {
    condition     = length(aws_route.private_nat) == 2
    error_message = "Every private route table needs a default route to the NAT."
  }
  assert {
    condition     = contains(keys(aws_nat_gateway.this), "ap-south-1a")
    error_message = "The single NAT gateway should live in the first zone."
  }
}

run "per_az_gives_each_zone_its_own_nat_gateway" {
  command = plan
  variables {
    nat_mode = "per_az"
    azs      = ["ap-south-1a", "ap-south-1b", "ap-south-1c"]
  }

  assert {
    condition     = length(aws_nat_gateway.this) == 3 && length(aws_eip.nat) == 3
    error_message = "nat_mode = per_az must create one NAT gateway per zone."
  }
  assert {
    condition     = toset(keys(aws_nat_gateway.this)) == toset(var.azs)
    error_message = "Each NAT gateway should be keyed by its zone."
  }
}

run "none_means_no_nat_and_no_internet_route_from_private_subnets" {
  command = plan
  variables {
    nat_mode = "none"
  }

  assert {
    condition     = length(aws_nat_gateway.this) == 0 && length(aws_eip.nat) == 0 && length(aws_route.private_nat) == 0
    error_message = "nat_mode = none must create no NAT gateway, no address and no default route."
  }
  assert {
    condition     = length(aws_subnet.private) == 2
    error_message = "The private subnets themselves must still exist."
  }
}

run "the_database_tier_never_gets_an_internet_route" {
  # `apply` against the MOCK provider (nothing real is created): resource ids only exist after an apply.
  command = apply
  variables {
    nat_mode = "per_az"
  }

  assert {
    condition     = !contains(concat([aws_route.public_internet.route_table_id], [for r in values(aws_route.private_nat) : r.route_table_id]), aws_route_table.database.id)
    error_message = "No default route may be attached to the database route table: databases must have no path to or from the internet."
  }
  assert {
    condition     = aws_route.public_internet.route_table_id == aws_route_table.public.id && aws_route.public_internet.gateway_id == aws_internet_gateway.this.id
    error_message = "The internet gateway route belongs to the public route table only."
  }
  assert {
    condition     = alltrue([for az, r in aws_route.private_nat : r.nat_gateway_id == aws_nat_gateway.this[az].id])
    error_message = "With per_az, every private route table must use the NAT gateway in its own zone."
  }
}

run "the_default_security_group_has_no_rules" {
  command = plan

  assert {
    condition     = length(aws_default_security_group.this.ingress) == 0 && length(aws_default_security_group.this.egress) == 0
    error_message = "The VPC's default security group must be emptied so forgetting to pick one allows nothing."
  }
}

run "kubernetes_discovery_tags" {
  command = plan
  variables {
    eks_cluster_name = "school-dev"
  }

  assert {
    condition     = aws_subnet.public["ap-south-1a"].tags["kubernetes.io/role/elb"] == "1" && aws_subnet.public["ap-south-1a"].tags["kubernetes.io/cluster/school-dev"] == "shared"
    error_message = "Public subnets need the elb role tag and the cluster tag."
  }
  assert {
    condition     = aws_subnet.private["ap-south-1a"].tags["kubernetes.io/role/internal-elb"] == "1"
    error_message = "Private subnets need the internal-elb role tag."
  }
}

run "no_cluster_tag_unless_a_cluster_is_named" {
  command = plan

  assert {
    condition     = !contains(keys(aws_subnet.private["ap-south-1a"].tags), "kubernetes.io/cluster/school-dev")
    error_message = "Without eks_cluster_name there must be no cluster tag."
  }
}

run "s3_endpoint_is_on_by_default_and_can_be_turned_off" {
  command = plan
  assert {
    condition     = length(aws_vpc_endpoint.s3) == 1
    error_message = "The free S3 gateway endpoint should be created by default."
  }
}

run "s3_endpoint_off" {
  command = plan
  variables {
    enable_s3_endpoint = false
  }
  assert {
    condition     = length(aws_vpc_endpoint.s3) == 0
    error_message = "enable_s3_endpoint = false must remove it."
  }
}

run "interface_endpoints_are_created_only_when_asked_for" {
  command = plan
  assert {
    condition     = length(aws_vpc_endpoint.interface) == 0 && length(aws_security_group.endpoints) == 0
    error_message = "No interface endpoints (and no security group for them) by default: they cost money."
  }
}

run "interface_endpoints_share_one_security_group" {
  command = plan
  variables {
    interface_endpoints = ["sqs", "sns", "secretsmanager"]
  }
  assert {
    condition     = length(aws_vpc_endpoint.interface) == 3 && length(aws_security_group.endpoints) == 1
    error_message = "Three endpoints and one shared security group expected."
  }
  assert {
    condition     = aws_vpc_endpoint.interface["sqs"].service_name == "com.amazonaws.ap-south-1.sqs" && aws_vpc_endpoint.interface["sqs"].private_dns_enabled
    error_message = "Endpoint names must include the region and use private DNS."
  }
}

run "flow_logs_off_by_default" {
  command = plan
  assert {
    condition     = length(aws_flow_log.this) == 0 && length(aws_cloudwatch_log_group.flow) == 0 && length(aws_iam_role.flow) == 0
    error_message = "Flow logs must be opt-in."
  }
}

run "flow_logs_on" {
  command = plan
  variables {
    enable_flow_logs         = true
    flow_logs_retention_days = 14
  }
  assert {
    condition     = length(aws_flow_log.this) == 1 && length(aws_cloudwatch_log_group.flow) == 1 && length(aws_iam_role.flow) == 1
    error_message = "Flow logs need a log group, a role and the flow log."
  }
  assert {
    condition     = aws_cloudwatch_log_group.flow[0].retention_in_days == 14 && aws_cloudwatch_log_group.flow[0].name == "/vpc/school-test/flow-logs"
    error_message = "Retention and naming should follow the inputs."
  }
}

run "everything_is_named_after_the_prefix" {
  command = plan
  assert {
    condition     = aws_vpc.this.tags["Name"] == "school-test" && aws_subnet.private["ap-south-1b"].tags["Name"] == "school-test-private-ap-south-1b"
    error_message = "Names follow <prefix>-<tier>-<zone>."
  }
}

run "rejects_a_vpc_range_that_is_not_a_slash_16" {
  command = plan
  variables {
    cidr_block = "10.10.0.0/20"
  }
  expect_failures = [var.cidr_block]
}

run "rejects_a_single_zone" {
  command = plan
  variables {
    azs = ["ap-south-1a"]
  }
  expect_failures = [var.azs]
}

run "rejects_duplicate_zones" {
  command = plan
  variables {
    azs = ["ap-south-1a", "ap-south-1a"]
  }
  expect_failures = [var.azs]
}

run "rejects_an_unknown_nat_mode" {
  command = plan
  variables {
    nat_mode = "sometimes"
  }
  expect_failures = [var.nat_mode]
}
