# aws is mocked. random is the REAL provider: it needs no credentials, and mock providers cannot mock ephemeral resources.
mock_provider "aws" {}

variables {
  name_prefix = "school/test"
  services    = ["auth", "fee"]
  db_host     = "school-test-db.abc.ap-south-1.rds.amazonaws.com"
  db_name     = "school"
}

run "two_logins_per_service_one_secret_each" {
  command = plan

  assert {
    condition     = toset(keys(aws_secretsmanager_secret.db)) == toset(["auth_app", "auth_migrator", "fee_app", "fee_migrator"])
    error_message = "Each service needs an app login and a migrator login."
  }
  assert {
    condition     = aws_secretsmanager_secret.db["fee_app"].name == "school/test/db/fee_app"
    error_message = "Secret names follow <prefix>/db/<service>_<kind>."
  }
}

run "usernames_match_the_database_roles" {
  command = plan

  assert {
    condition     = aws_secretsmanager_secret.db["fee_app"].description == "PostgreSQL login fee_svc for the fee service" && aws_secretsmanager_secret.db["auth_migrator"].description == "PostgreSQL login auth_migrator for the auth service"
    error_message = "The login names must be <service>_svc and <service>_migrator, exactly as scripts/db/service_roles.sql creates them."
  }
}

run "passwords_are_written_with_a_write_only_argument_and_a_version_number" {
  command = plan
  variables {
    credentials_version = 3
  }

  assert {
    condition     = alltrue([for v in values(aws_secretsmanager_secret_version.db) : v.secret_string_wo_version == 3])
    error_message = "The version number is what triggers writing a new password."
  }
  assert {
    condition     = alltrue([for v in values(aws_secretsmanager_secret_version.db) : v.secret_string == null])
    error_message = "The ordinary (stored-in-state) secret_string must not be used for passwords."
  }
}

run "the_signing_key_secrets_are_empty_containers" {
  command = plan

  assert {
    condition     = aws_secretsmanager_secret.jwt_private.name == "school/test/jwt/private-key" && aws_secretsmanager_secret.jwt_public.name == "school/test/jwt/public-key"
    error_message = "Two containers for the signing key pair."
  }
}

run "recovery_window_defaults_to_a_week_and_dev_can_skip_it" {
  command = plan

  assert {
    condition     = alltrue([for s in values(aws_secretsmanager_secret.db) : s.recovery_window_in_days == 7])
    error_message = "A deleted secret can be restored for 7 days by default."
  }
}

run "dev_can_delete_immediately" {
  command = plan
  variables {
    recovery_window_days = 0
  }

  assert {
    condition     = aws_secretsmanager_secret.jwt_private.recovery_window_in_days == 0
    error_message = "0 means delete immediately."
  }
}

run "rejects_a_recovery_window_of_three_days" {
  command = plan
  variables {
    recovery_window_days = 3
  }
  expect_failures = [var.recovery_window_days]
}
