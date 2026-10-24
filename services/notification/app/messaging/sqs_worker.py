import logging
import threading
from pathlib import Path

from app.services.event_processor import EventProcessor, Outcome, PoisonMessage

logger = logging.getLogger(__name__)


def retry_delay(receive_count: int, base: int, cap: int) -> int:
    """Exponential backoff: 30s, 60s, 120s ... up to the cap. receive_count starts at 1."""
    return min(base * 2 ** max(receive_count - 1, 0), cap)


class SqsWorker:
    """Long-polls the queue and hands each message to the EventProcessor.

    A message is deleted only after it is fully handled. Anything else (a crash, a failed delivery, an
    unexpected error) leaves it in the queue, and SQS gives it back after the visibility timeout. After
    `maxReceiveCount` tries SQS moves it to the dead-letter queue (configured in Terraform, Phase 13).
    """

    def __init__(
        self,
        client,
        queue_url: str,
        processor: EventProcessor,
        *,
        wait_seconds: int,
        batch_size: int,
        retry_base: int,
        retry_cap: int,
        heartbeat_file: str | None = None,
    ) -> None:
        self._client = client
        self._queue_url = queue_url
        self._processor = processor
        self._wait = wait_seconds
        self._batch = batch_size
        self._retry_base = retry_base
        self._retry_cap = retry_cap
        self._heartbeat = Path(heartbeat_file) if heartbeat_file else None

    def poll_once(self) -> int:
        """Receive and process one batch. Returns how many messages were received."""
        response = self._client.receive_message(
            QueueUrl=self._queue_url,
            MaxNumberOfMessages=self._batch,
            WaitTimeSeconds=self._wait,
            AttributeNames=["ApproximateReceiveCount"],
        )
        messages = response.get("Messages", [])
        for message in messages:
            self._handle(message)
        return len(messages)

    def _handle(self, message: dict) -> None:
        receipt = message["ReceiptHandle"]
        receive_count = int(message.get("Attributes", {}).get("ApproximateReceiveCount", "1"))
        try:
            outcome = self._processor.handle(message["Body"])
        except PoisonMessage:
            logger.exception("poison message left for the dead-letter queue", extra={"receive_count": receive_count})
            return
        except Exception:
            logger.exception("unexpected error; message will be redelivered", extra={"receive_count": receive_count})
            return
        if outcome is Outcome.DONE:
            self._client.delete_message(QueueUrl=self._queue_url, ReceiptHandle=receipt)
        else:
            delay = retry_delay(receive_count, self._retry_base, self._retry_cap)
            self._client.change_message_visibility(
                QueueUrl=self._queue_url, ReceiptHandle=receipt, VisibilityTimeout=delay
            )
            logger.info("will retry later", extra={"delay_seconds": delay, "receive_count": receive_count})

    def _beat(self) -> None:
        if self._heartbeat:
            try:
                self._heartbeat.touch()
            except OSError:
                logger.warning("could not write heartbeat file")

    def run(self, stop: threading.Event) -> None:
        logger.info("worker started")
        while not stop.is_set():
            self._beat()  # a Kubernetes probe restarts the pod if this file goes stale
            try:
                self.poll_once()
            except Exception:  # e.g. SQS briefly unreachable: back off instead of spinning
                logger.exception("polling failed")
                stop.wait(5)
        logger.info("worker stopped")
