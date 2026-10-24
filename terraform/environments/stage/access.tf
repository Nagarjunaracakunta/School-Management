# ---- who may do what (least privilege) -----------------------------------------------------------------------------------
# One IAM role per service. Each lists EXACTLY what it needs; the iam module refuses wildcards. Pods receive their role
# through EKS Pod Identity (the associations are created in Phase 14).
locals {
  pod_roles = merge(
    {
      for svc in local.services : svc => {
        description = "Permissions of the ${svc} service's pods"
        statements = concat(
          # every service: read ITS OWN database login, and the public key that verifies tokens
          [
            { sid = "ReadOwnDatabaseLogin", actions = ["secretsmanager:GetSecretValue"], resources = [module.secrets.db_secret_arns["${svc}_app"]] },
            { sid = "ReadTokenVerificationKey", actions = ["secretsmanager:GetSecretValue"], resources = [module.secrets.jwt_public_secret_arn] },
          ],
          # only Auth can read the key that SIGNS tokens
          svc == "auth" ? [
            { sid = "ReadTokenSigningKey", actions = ["secretsmanager:GetSecretValue"], resources = [module.secrets.jwt_private_secret_arn] },
          ] : [],
          # producers may send events to the queue; they cannot read or delete them
          contains(local.event_producers, svc) ? [
            { sid = "PublishEvents", actions = ["sqs:SendMessage"], resources = [module.events.queue_arn] },
          ] : [],
          # the consumer may read and delete events, and hand messages to the notifications topic; it cannot send events
          svc == local.event_consumer ? [
            { sid = "ConsumeEvents", actions = ["sqs:ReceiveMessage", "sqs:DeleteMessage", "sqs:ChangeMessageVisibility", "sqs:GetQueueAttributes"], resources = [module.events.queue_arn] },
            { sid = "PublishNotifications", actions = ["sns:Publish"], resources = [module.notifications_topic.topic_arn] },
          ] : [],
        )
      }
    },
    {
      # The job that creates the per-service database roles and runs migrations (Phase 15). It is the ONLY role that can
      # read the administrator login and the migrator logins.
      "db-migrator" = {
        description = "Database bootstrap and migration jobs"
        statements = [
          { sid = "ReadDatabaseAdministratorLogin", actions = ["secretsmanager:GetSecretValue"], resources = [module.rds.master_user_secret_arn] },
          { sid = "ReadAllMigratorLogins", actions = ["secretsmanager:GetSecretValue"], resources = [for svc in local.services : module.secrets.db_secret_arns["${svc}_migrator"]] },
          { sid = "ReadAllAppLogins", actions = ["secretsmanager:GetSecretValue"], resources = [for svc in local.services : module.secrets.db_secret_arns["${svc}_app"]] },
        ]
      }
    },
  )
}

module "pod_roles" {
  source = "../../modules/iam"

  name_prefix = local.name_prefix
  roles       = local.pod_roles
}
