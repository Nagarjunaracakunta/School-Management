# Run with the environment's own values:   terraform test -var-file=terraform.tfvars
# The AWS provider is mocked, so this needs no account and no credentials.
mock_provider "archive" {
  mock_data "archive_file" {
    defaults = {
      output_path         = "/tmp/fn.zip"
      output_base64sha256 = "bW9ja2VkLWhhc2g="
    }
  }
}

mock_provider "aws" {
  mock_data "aws_ec2_managed_prefix_list" {
    defaults = {
      id = "pl-0123456789abcdef0"
    }
  }
  mock_data "aws_caller_identity" {
    defaults = {
      account_id = "123456789012"
    }
  }
  mock_data "aws_availability_zones" {
    defaults = {
      names = ["ap-south-1a", "ap-south-1b", "ap-south-1c"]
    }
  }
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

run "the_committed_values_pass_every_guardrail_and_build_the_network" {
  command = plan

  assert {
    condition     = length(module.vpc.azs) == var.az_count
    error_message = "The VPC should span az_count zones."
  }
  assert {
    condition     = length(module.vpc.public_subnet_ids) == var.az_count && length(module.vpc.private_subnet_ids) == var.az_count && length(module.vpc.database_subnet_ids) == var.az_count
    error_message = "Each tier should have one subnet per zone."
  }
}

run "only_the_registry_owner_creates_repositories" {
  command = plan

  assert {
    condition     = length(module.ecr) == (var.manage_ecr ? 1 : 0)
    error_message = "ECR repositories must be created exactly where manage_ecr is true."
  }
}

run "resources_are_named_after_the_environment" {
  command = plan

  assert {
    condition     = local.name_prefix == "${var.project}-${var.environment}"
    error_message = "Names must start with <project>-<environment>."
  }
}

run "production_refuses_a_single_nat_gateway" {
  command = plan
  variables {
    environment = "prod"
    nat_mode    = "single"
    az_count    = 3
  }
  expect_failures = [terraform_data.guardrails]
}

run "production_refuses_two_zones" {
  command = plan
  variables {
    environment = "prod"
    nat_mode    = "per_az"
    az_count    = 2
  }
  expect_failures = [terraform_data.guardrails]
}

run "production_refuses_to_run_without_flow_logs" {
  command = plan
  variables {
    environment      = "prod"
    nat_mode         = "per_az"
    az_count         = 3
    enable_flow_logs = false
  }
  expect_failures = [terraform_data.guardrails]
}

run "an_unknown_environment_name_is_rejected" {
  command = plan
  variables {
    environment = "qa"
  }
  expect_failures = [var.environment]
}

# ---- least privilege: what each service's IAM role can actually do ----------------------------------------------------
# (local.pod_roles is what is handed to the iam module; the module itself refuses wildcards)

run "there_is_one_role_per_service_plus_the_database_job" {
  command = plan

  assert {
    condition     = toset(keys(local.pod_roles)) == toset(["auth", "admission", "student", "fee", "attendance", "notification", "db-migrator"])
    error_message = "Six services and the database bootstrap/migration job."
  }
}

run "services_that_publish_events_can_send_but_never_receive_or_delete" {
  command = plan

  assert {
    condition     = alltrue([for svc in ["admission", "fee", "attendance"] : contains(flatten([for st in local.pod_roles[svc].statements : st.actions]), "sqs:SendMessage")])
    error_message = "Admission, Fee and Attendance publish events."
  }
  assert {
    condition     = alltrue([for svc in ["admission", "fee", "attendance"] : !anytrue([for a in flatten([for st in local.pod_roles[svc].statements : st.actions]) : contains(["sqs:ReceiveMessage", "sqs:DeleteMessage"], a)])])
    error_message = "A producer must not be able to read or delete other services' events."
  }
}

run "only_the_notification_service_consumes_events_and_publishes_to_the_topic" {
  command = plan

  assert {
    condition     = contains(flatten([for st in local.pod_roles["notification"].statements : st.actions]), "sqs:ReceiveMessage") && contains(flatten([for st in local.pod_roles["notification"].statements : st.actions]), "sqs:DeleteMessage") && contains(flatten([for st in local.pod_roles["notification"].statements : st.actions]), "sns:Publish")
    error_message = "The worker must consume the queue and publish to SNS."
  }
  assert {
    condition     = !contains(flatten([for st in local.pod_roles["notification"].statements : st.actions]), "sqs:SendMessage")
    error_message = "The consumer must not be able to inject events."
  }
  assert {
    condition     = alltrue([for svc in ["auth", "student", "admission", "fee", "attendance"] : !contains(flatten([for st in local.pod_roles[svc].statements : st.actions]), "sns:Publish")])
    error_message = "Nobody else may publish notifications."
  }
}

run "auth_and_student_have_no_queue_access_at_all" {
  command = plan

  assert {
    condition     = alltrue([for svc in ["auth", "student"] : !anytrue([for a in flatten([for st in local.pod_roles[svc].statements : st.actions]) : startswith(a, "sqs:")])])
    error_message = "Auth and Student neither publish nor consume events."
  }
}

run "only_auth_can_read_the_token_signing_key" {
  command = plan

  assert {
    condition     = [for svc in local.services : svc if contains([for st in local.pod_roles[svc].statements : st.sid], "ReadTokenSigningKey")] == ["auth"]
    error_message = "The private signing key may be read by the Auth service and nobody else."
  }
}

run "every_service_reads_exactly_its_own_database_login" {
  command = plan

  assert {
    condition     = alltrue([for svc in local.services : length([for st in local.pod_roles[svc].statements : st if st.sid == "ReadOwnDatabaseLogin"]) == 1])
    error_message = "One statement for the service's own login."
  }
  assert {
    condition     = alltrue([for svc in local.services : length(one([for st in local.pod_roles[svc].statements : st if st.sid == "ReadOwnDatabaseLogin"]).resources) == 1])
    error_message = "That statement names exactly one secret, not a pattern."
  }
}

run "only_the_database_job_can_read_the_administrator_and_migrator_logins" {
  command = plan

  assert {
    condition     = [for k, r in local.pod_roles : k if contains([for st in r.statements : st.sid], "ReadDatabaseAdministratorLogin")] == ["db-migrator"]
    error_message = "The administrator login is for the bootstrap job only."
  }
  assert {
    condition     = [for k, r in local.pod_roles : k if contains([for st in r.statements : st.sid], "ReadAllMigratorLogins")] == ["db-migrator"]
    error_message = "Only the migration job may read migrator (schema-changing) logins."
  }
}

run "no_role_is_given_a_wildcard_anywhere" {
  command = plan

  assert {
    condition     = !anytrue(flatten([for r in local.pod_roles : [for st in r.statements : [for a in st.actions : endswith(a, "*")]]]))
    error_message = "No wildcard actions in any role."
  }
}

# ---- production guardrails for the data layer ---------------------------------------------------------------------------------

run "production_database_must_be_multi_az" {
  command = plan
  variables {
    environment      = "prod"
    nat_mode         = "per_az"
    az_count         = 3
    enable_flow_logs = true
    rds_multi_az     = false
  }
  expect_failures = [terraform_data.guardrails]
}

run "production_database_must_keep_a_week_of_backups" {
  command = plan
  variables {
    environment               = "prod"
    nat_mode                  = "per_az"
    az_count                  = 3
    enable_flow_logs          = true
    rds_multi_az              = true
    rds_deletion_protection   = true
    rds_skip_final_snapshot   = false
    rds_backup_retention_days = 3
  }
  expect_failures = [terraform_data.guardrails]
}

run "production_database_must_be_protected_from_deletion" {
  command = plan
  variables {
    environment             = "prod"
    nat_mode                = "per_az"
    az_count                = 3
    enable_flow_logs        = true
    rds_multi_az            = true
    rds_deletion_protection = false
  }
  expect_failures = [terraform_data.guardrails]
}

run "production_must_not_allow_force_deleting_the_frontend" {
  command = plan
  variables {
    environment             = "prod"
    nat_mode                = "per_az"
    az_count                = 3
    enable_flow_logs        = true
    rds_multi_az            = true
    rds_deletion_protection = true
    rds_skip_final_snapshot = false
    frontend_force_destroy  = true
  }
  expect_failures = [terraform_data.guardrails]
}

# ---- monitoring --------------------------------------------------------------------------------------------------------------

run "every_alarm_we_expect_exists" {
  command = plan

  # 2 dead-letter style queues + 1 queue-age + 3 database + 1 delivery-function alarm
  assert {
    condition     = length(module.observability.alarm_names) == 7
    error_message = "Expected 7 alarms."
  }
}

# ---- Kubernetes ---------------------------------------------------------------------------------------------------------------

run "the_database_accepts_postgres_traffic_only_from_the_cluster" {
  command = plan

  assert {
    condition     = aws_vpc_security_group_ingress_rule.database_from_cluster.from_port == 5432 && aws_vpc_security_group_ingress_rule.database_from_cluster.to_port == 5432 && aws_vpc_security_group_ingress_rule.database_from_cluster.ip_protocol == "tcp"
    error_message = "Exactly TCP 5432."
  }
  assert {
    condition     = aws_vpc_security_group_ingress_rule.database_from_cluster.cidr_ipv4 == null && aws_vpc_security_group_ingress_rule.database_from_cluster.cidr_ipv6 == null
    error_message = "The source must be the cluster's security group, never an address range."
  }
}

run "every_iam_role_is_connected_to_a_service_account_of_the_same_name_in_the_environments_namespace" {
  command = plan

  assert {
    condition     = toset(keys(local.pod_identity_associations)) == toset(keys(local.pod_roles))
    error_message = "One association for each of the six services and the database job."
  }
  assert {
    condition     = alltrue([for k, a in local.pod_identity_associations : a.service_account == k && a.namespace == "${var.project}-${var.environment}"])
    error_message = "Service account = service name; namespace = school-<environment>. The Helm charts must match."
  }
}

run "the_kubernetes_namespace_matches_the_resource_prefix" {
  command = plan

  assert {
    condition     = local.kubernetes_namespace == local.name_prefix
    error_message = "One name for everything: school-dev, school-stage, school-prod."
  }
}

run "production_needs_at_least_two_nodes_always_running" {
  command = plan
  variables {
    environment             = "prod"
    nat_mode                = "per_az"
    az_count                = 3
    enable_flow_logs        = true
    rds_multi_az            = true
    rds_deletion_protection = true
    rds_skip_final_snapshot = false
    node_min_size           = 1
    node_desired_size       = 3
  }
  expect_failures = [terraform_data.guardrails]
}

run "node_counts_must_be_in_order" {
  command = plan
  variables {
    node_min_size     = 3
    node_desired_size = 2
    node_max_size     = 4
  }
  expect_failures = [terraform_data.guardrails]
}

# ---- the load balancer's firewall ---------------------------------------------------------------------------------------------

run "the_load_balancer_accepts_one_port_from_cloudfront_and_nobody_else" {
  command = plan

  assert {
    condition     = aws_vpc_security_group_ingress_rule.alb_from_cloudfront.from_port == (var.api_origin_protocol == "https" ? 443 : 80) && aws_vpc_security_group_ingress_rule.alb_from_cloudfront.to_port == aws_vpc_security_group_ingress_rule.alb_from_cloudfront.from_port
    error_message = "One port only (443, or 80 in the dev trial without a certificate): the CloudFront prefix list already uses most of the security group's rule quota."
  }
  assert {
    condition     = aws_vpc_security_group_ingress_rule.alb_from_cloudfront.prefix_list_id != null && aws_vpc_security_group_ingress_rule.alb_from_cloudfront.cidr_ipv4 == null
    error_message = "The source is CloudFront's managed prefix list, never an address range such as 0.0.0.0/0."
  }
}

run "environments_without_a_registry_know_where_to_pull_from" {
  command = plan
  variables {
    manage_ecr           = false
    ecr_owner_account_id = ""
  }
  expect_failures = [terraform_data.guardrails]
}

run "the_registry_host_name_is_built_from_the_owning_account" {
  command = plan

  assert {
    condition     = var.manage_ecr || local.image_registry == "${var.ecr_owner_account_id}.dkr.ecr.${var.aws_region}.amazonaws.com"
    error_message = "stage and prod pull from the account that owns the registry (dev)."
  }
}

run "the_registry_holds_an_image_for_every_service_and_for_the_database_tool" {
  command = plan

  assert {
    condition     = toset(local.ecr_repositories) == toset(["auth", "admission", "student", "fee", "attendance", "notification", "db-tools"])
    error_message = "Six services and the db-tools image used by the database bootstrap job."
  }
}

run "only_the_registry_owner_gets_the_image_push_role_but_every_environment_can_publish_its_website" {
  command = plan

  assert {
    condition     = length(module.github_oidc.subject) > 0 && module.github_oidc.frontend_subject == "repo:${var.github_repository}:environment:frontend-${var.environment}"
    error_message = "The website role trusts the GitHub Environment named frontend-<environment>."
  }
}
