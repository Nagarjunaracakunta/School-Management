locals {
  # Every resource is named <project>-<environment>-<what>, for example school-prod-vpc.
  name_prefix = "${var.project}-${var.environment}"

  # Take the first N zones AWS offers in this region. The data source is in main.tf.
  azs = slice(data.aws_availability_zones.available.names, 0, var.az_count)

  # One container image per deployable service (the Notification worker uses the notification image).
  services = ["auth", "admission", "student", "fee", "attendance", "notification"]

  # Container images to keep in the registry: one per service, plus the tool that creates the database roles (Helm: school-platform).
  ecr_repositories = concat(local.services, ["db-tools"])

  # Services that publish events to the queue (decision D3 and the outbox pattern), and the one that consumes them.
  event_producers = ["admission", "fee", "attendance"]
  event_consumer  = "notification"

  # The Kubernetes namespace all services run in. The Helm charts (Phase 15) must use this exact name.
  kubernetes_namespace = local.name_prefix

  # Secrets Manager names look like  school/dev/db/fee_app
  secret_prefix = "${var.project}/${var.environment}"
}
