variable "name" {
  description = "Name prefix for the alarms, for example school-dev."
  type        = string
}

variable "alarm_topic_arn" {
  description = "SNS topic that receives every alarm (and its recovery)."
  type        = string
}

variable "dead_letter_queue_names" {
  description = "Names of dead-letter queues. ANY message in one is a problem a human must look at."
  type        = set(string)
  default     = []
}

variable "queue_names" {
  description = "Names of working queues, watched for messages that are not being consumed."
  type        = set(string)
  default     = []
}

variable "queue_max_age_seconds" {
  description = "Alarm when the oldest message in a working queue is older than this."
  type        = number
  default     = 900
}

variable "rds_instance_id" {
  description = "Database to watch. null = none."
  type        = string
  default     = null
}

variable "rds_cpu_percent" {
  description = "Alarm above this CPU use."
  type        = number
  default     = 80
}

variable "rds_free_storage_bytes" {
  description = "Alarm below this free disk space (default 5 GiB)."
  type        = number
  default     = 5368709120
}

variable "rds_connections" {
  description = "Alarm above this many open connections."
  type        = number
  default     = 80
}

variable "lambda_function_names" {
  description = "Functions whose errors should raise an alarm."
  type        = set(string)
  default     = []
}

variable "tags" {
  description = "Extra tags."
  type        = map(string)
  default     = {}
}
