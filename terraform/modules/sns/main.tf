data "aws_caller_identity" "current" {}

resource "aws_sns_topic" "this" {
  name              = var.name
  kms_master_key_id = var.kms_master_key_id

  tags = merge(var.tags, { Name = var.name })
}

data "aws_iam_policy_document" "this" {
  statement {
    sid       = "DenyInsecureTransport"
    effect    = "Deny"
    actions   = ["sns:Publish", "sns:Subscribe"]
    resources = [aws_sns_topic.this.arn]

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

  # Everything else is governed by IAM in this account (the default topic policy is replaced, so say it explicitly):
  statement {
    sid       = "AccountOwnerManagesTheTopic"
    effect    = "Allow"
    actions   = ["sns:GetTopicAttributes", "sns:SetTopicAttributes", "sns:Subscribe", "sns:ListSubscriptionsByTopic", "sns:Publish"]
    resources = [aws_sns_topic.this.arn]

    principals {
      type        = "AWS"
      identifiers = ["arn:aws:iam::${data.aws_caller_identity.current.account_id}:root"]
    }
  }

  dynamic "statement" {
    for_each = var.allow_cloudwatch_alarms ? [1] : []

    content {
      sid       = "AllowCloudWatchAlarms"
      effect    = "Allow"
      actions   = ["sns:Publish"]
      resources = [aws_sns_topic.this.arn]

      principals {
        type        = "Service"
        identifiers = ["cloudwatch.amazonaws.com"]
      }

      # Only alarms from THIS account, not any alarm anywhere that names this topic (the "confused deputy" problem)
      condition {
        test     = "StringEquals"
        variable = "aws:SourceAccount"
        values   = [data.aws_caller_identity.current.account_id]
      }
    }
  }
}

resource "aws_sns_topic_policy" "this" {
  arn    = aws_sns_topic.this.arn
  policy = data.aws_iam_policy_document.this.json
}

resource "aws_sns_topic_subscription" "this" {
  for_each = var.subscriptions

  topic_arn            = aws_sns_topic.this.arn
  protocol             = each.value.protocol
  endpoint             = each.value.endpoint
  filter_policy        = each.value.filter_policy
  filter_policy_scope  = each.value.filter_policy == null ? null : "MessageAttributes"
  raw_message_delivery = each.value.raw_message_delivery
}
