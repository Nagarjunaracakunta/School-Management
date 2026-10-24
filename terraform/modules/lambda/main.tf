data "archive_file" "code" {
  type        = "zip"
  source_dir  = var.source_dir
  output_path = "${path.module}/.build/${var.name}.zip"
  excludes    = ["tests", "__pycache__", ".pytest_cache", "requirements-dev.txt"]
}

# Created by us so the retention is set. A Lambda creates its own log group on first run, with logs kept forever.
resource "aws_cloudwatch_log_group" "this" {
  name              = "/aws/lambda/${var.name}"
  retention_in_days = var.log_retention_days

  tags = var.tags
}

resource "aws_iam_role" "this" {
  name = var.name

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "lambda.amazonaws.com" }
      Action    = "sts:AssumeRole"
    }]
  })

  tags = var.tags
}

locals {
  statements = concat(
    # Write logs to its OWN log group, nothing broader.
    [{
      Sid      = "WriteOwnLogs"
      Effect   = "Allow"
      Action   = ["logs:CreateLogStream", "logs:PutLogEvents"]
      Resource = ["${aws_cloudwatch_log_group.this.arn}:*"]
    }],
    [for s in var.statements : { Sid = s.sid, Effect = "Allow", Action = s.actions, Resource = s.resources }],
    var.failure_queue == null ? [] : [{
      Sid      = "WriteFailedInvocationsToQueue"
      Effect   = "Allow"
      Action   = ["sqs:SendMessage"]
      Resource = [var.failure_queue.arn]
    }],
    # Texting a phone number cannot be limited to a resource in IAM, so this one Allow needs "*". The Deny right after
    # it removes the danger: the function can send texts but can never publish to any SNS TOPIC.
    var.allow_sms_publish ? [
      { Sid = "SendTextMessages", Effect = "Allow", Action = ["sns:Publish"], Resource = ["*"] },
      { Sid = "NeverPublishToTopics", Effect = "Deny", Action = ["sns:Publish"], Resource = ["arn:aws:sns:*:*:*"] },
    ] : [],
  )
}

resource "aws_iam_role_policy" "this" {
  name = "permissions"
  role = aws_iam_role.this.id

  policy = jsonencode({
    Version   = "2012-10-17"
    Statement = local.statements
  })
}

resource "aws_lambda_function" "this" {
  function_name = var.name
  role          = aws_iam_role.this.arn

  filename         = data.archive_file.code.output_path
  source_code_hash = data.archive_file.code.output_base64sha256 # redeploy exactly when the code changes
  handler          = var.handler
  runtime          = var.runtime
  architectures    = ["arm64"] # Graviton: cheaper for the same work

  timeout                        = var.timeout_seconds
  memory_size                    = var.memory_mb
  reserved_concurrent_executions = var.reserved_concurrency

  dynamic "environment" {
    for_each = length(var.environment) > 0 ? [1] : []

    content {
      variables = var.environment
    }
  }

  dynamic "dead_letter_config" {
    for_each = var.failure_queue == null ? [] : [var.failure_queue]

    content {
      target_arn = dead_letter_config.value.arn
    }
  }

  tags = var.tags

  depends_on = [aws_cloudwatch_log_group.this, aws_iam_role_policy.this]
}

resource "aws_lambda_function_event_invoke_config" "this" {
  function_name          = aws_lambda_function.this.function_name
  maximum_retry_attempts = var.retry_attempts
}

# ---- trigger: SNS -----------------------------------------------------------------------------------------------------
resource "aws_lambda_permission" "sns" {
  count = var.sns_trigger == null ? 0 : 1

  statement_id  = "AllowInvokeFromSns"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.this.function_name
  principal     = "sns.amazonaws.com"
  source_arn    = var.sns_trigger.topic_arn # only THIS topic may invoke the function
}

resource "aws_sns_topic_subscription" "this" {
  count = var.sns_trigger == null ? 0 : 1

  topic_arn           = var.sns_trigger.topic_arn
  protocol            = "lambda"
  endpoint            = aws_lambda_function.this.arn
  filter_policy       = var.sns_trigger.filter_policy
  filter_policy_scope = var.sns_trigger.filter_policy == null ? null : "MessageAttributes"

  depends_on = [aws_lambda_permission.sns]
}
