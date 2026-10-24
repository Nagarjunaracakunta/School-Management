"""LOCAL ONLY: creates the queue, dead-letter queue and topic the platform expects, inside the moto AWS emulator.
In AWS, Terraform creates these (Phase 13). Safe to run repeatedly.

A "delivery-sink" queue is subscribed to the topic so you can SEE what the Notification Service handed to SNS:
    docker compose exec notification python -c "..."   (or any SQS client pointed at the emulator)
"""

import json

import boto3

sqs, sns = boto3.client("sqs"), boto3.client("sns")

dlq = sqs.create_queue(QueueName="school-events-dlq")["QueueUrl"]
dlq_arn = sqs.get_queue_attributes(QueueUrl=dlq, AttributeNames=["QueueArn"])["Attributes"]["QueueArn"]
queue = sqs.create_queue(
    QueueName="school-events",
    Attributes={
        # After 3 failed receives a message moves to the DLQ instead of being retried forever
        "RedrivePolicy": json.dumps({"deadLetterTargetArn": dlq_arn, "maxReceiveCount": "3"}),
        "VisibilityTimeout": "60",
    },
)["QueueUrl"]
topic = sns.create_topic(Name="school-notifications")["TopicArn"]
sink = sqs.create_queue(QueueName="delivery-sink")["QueueUrl"]
sink_arn = sqs.get_queue_attributes(QueueUrl=sink, AttributeNames=["QueueArn"])["Attributes"]["QueueArn"]
sns.subscribe(TopicArn=topic, Protocol="sqs", Endpoint=sink_arn)

print(f"queue: {queue}\ndlq:   {dlq}\ntopic: {topic}\nsink:  {sink}")
