# Test fixture: a topic and a queue created in the SAME configuration as the function, so their ARNs are unknown at plan time.
terraform {
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 6.0"
    }
  }
}

variable "source_dir" {
  type = string
}

resource "aws_sns_topic" "t" {
  name = "fixture-topic"
}

resource "aws_sqs_queue" "q" {
  name = "fixture-failures"
}

module "fn" {
  source = "../../.."

  name          = "fixture-fn"
  source_dir    = var.source_dir
  sns_trigger   = { topic_arn = aws_sns_topic.t.arn }
  failure_queue = { arn = aws_sqs_queue.q.arn }
}

output "trigger_count" {
  value = length(module.fn.subscription_arns)
}
