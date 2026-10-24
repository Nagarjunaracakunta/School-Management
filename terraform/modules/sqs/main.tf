# The dead-letter queue is created FIRST: the main queue's redrive policy refers to it.
resource "aws_sqs_queue" "dlq" {
  name                      = "${var.name}-dlq"
  message_retention_seconds = var.dlq_retention_days * 86400

  # Encrypted at rest either way: SQS-managed by default, or the given KMS key.
  sqs_managed_sse_enabled = var.kms_master_key_id == null ? true : null
  kms_master_key_id       = var.kms_master_key_id

  tags = merge(var.tags, { Name = "${var.name}-dlq" })
}

resource "aws_sqs_queue" "main" {
  name                       = var.name
  visibility_timeout_seconds = var.visibility_timeout_seconds
  message_retention_seconds  = var.message_retention_days * 86400
  receive_wait_time_seconds  = 20 # long polling by default: fewer empty responses, lower cost, lower latency

  sqs_managed_sse_enabled = var.kms_master_key_id == null ? true : null
  kms_master_key_id       = var.kms_master_key_id

  redrive_policy = jsonencode({
    deadLetterTargetArn = aws_sqs_queue.dlq.arn
    maxReceiveCount     = var.max_receive_count
  })

  tags = merge(var.tags, { Name = var.name })
}

# Only THIS queue may use the dead-letter queue. Without it, any queue in the account could dump messages into it.
resource "aws_sqs_queue_redrive_allow_policy" "dlq" {
  queue_url = aws_sqs_queue.dlq.id

  redrive_allow_policy = jsonencode({
    redrivePermission = "byQueue"
    sourceQueueArns   = [aws_sqs_queue.main.arn]
  })
}

# Who may send and receive is decided by the IAM roles of the services (least privilege, see the iam module). The queue
# policy adds one rule everyone must obey: no unencrypted connections.
data "aws_iam_policy_document" "tls_only" {
  for_each = { main = aws_sqs_queue.main.arn, dlq = aws_sqs_queue.dlq.arn }

  statement {
    sid       = "DenyInsecureTransport"
    effect    = "Deny"
    actions   = ["sqs:*"]
    resources = [each.value]

    principals {
      type        = "*"
      identifiers = ["*"]
    }

    condition {
      test     = "Bool"
      variable = "aws:SecureTransport"
      values   = ["false"]
    }
  }
}

resource "aws_sqs_queue_policy" "tls_only" {
  for_each = { main = aws_sqs_queue.main.id, dlq = aws_sqs_queue.dlq.id }

  queue_url = each.value
  policy    = data.aws_iam_policy_document.tls_only[each.key].json
}
