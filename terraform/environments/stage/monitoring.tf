# ---- alarms ------------------------------------------------------------------------------------------------------------------
module "observability" {
  source = "../../modules/observability"

  name            = local.name_prefix
  alarm_topic_arn = module.alerts_topic.topic_arn

  # Anything sitting in either queue means a message or a delivery failed every retry
  dead_letter_queue_names = [module.events.dlq_name, module.delivery_failures.queue_name]
  queue_names             = [module.events.queue_name]
  rds_instance_id         = module.rds.instance_id
  lambda_function_names   = [module.notification_delivery.function_name]
}
