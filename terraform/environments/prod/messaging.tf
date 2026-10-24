# ---- the event queue and its dead-letter queue (services publish, the Notification worker consumes) --------------------
module "events" {
  source = "../../modules/sqs"

  name = "${local.name_prefix}-events"
}

# ---- the notifications topic: the Notification Service publishes one message per recipient, the delivery function sends it
module "notifications_topic" {
  source = "../../modules/sns"

  name              = "${local.name_prefix}-notifications"
  kms_master_key_id = "alias/aws/sns" # messages contain names and contact details: encrypted at rest
}

# ---- the alerts topic: every CloudWatch alarm lands here, and people subscribe by email -------------------------------------
module "alerts_topic" {
  source = "../../modules/sns"

  name                    = "${local.name_prefix}-alerts"
  allow_cloudwatch_alarms = true # not encrypted: CloudWatch cannot publish to a topic using an AWS-managed key

  subscriptions = {
    for email in var.alert_emails : email => { protocol = "email", endpoint = email }
  }
}

# ---- email delivery: SES needs a verified sender -------------------------------------------------------------------------
# AWS sends a confirmation link to this address; until someone clicks it, SES refuses to send. In a new AWS account SES also
# starts in a "sandbox" that only delivers to verified recipients: request production access in the console before launch.
resource "aws_sesv2_email_identity" "sender" {
  count = var.ses_from_address == "" ? 0 : 1

  email_identity = var.ses_from_address
}

# Where a delivery that still fails after the retries is parked, so it is not silently lost (and an alarm fires).
module "delivery_failures" {
  source = "../../modules/sqs"

  name                   = "${local.name_prefix}-delivery-failures"
  message_retention_days = 14
}

# ---- the delivery function: SNS -> SES (email) / SMS ------------------------------------------------------------------------
module "notification_delivery" {
  source = "../../modules/lambda"

  name       = "${local.name_prefix}-notification-delivery"
  source_dir = "${path.root}/../../../lambdas/notification_delivery"

  environment = {
    FROM_ADDRESS  = var.ses_from_address
    SMS_SENDER_ID = var.sms_sender_id
  }

  statements = var.ses_from_address == "" ? [] : [
    { sid = "SendEmailFromOurAddressOnly", actions = ["ses:SendEmail"], resources = [aws_sesv2_email_identity.sender[0].arn] },
  ]
  allow_sms_publish = true

  sns_trigger = {
    topic_arn     = module.notifications_topic.topic_arn
    filter_policy = jsonencode({ channel = ["EMAIL", "SMS"] })
  }
  failure_queue        = { arn = module.delivery_failures.queue_arn }
  reserved_concurrency = var.delivery_max_concurrency
}
