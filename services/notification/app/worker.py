"""Entry point of the queue consumer:  python -m app.worker

Runs in its own Deployment (same image as the API, different command), so it can be scaled and restarted
independently of the HTTP API.
"""

import logging
import signal
import threading

import boto3

from app.config.database import build_engine, build_session_factory
from app.config.settings import get_settings
from app.messaging.factory import build_deliverer
from app.messaging.sqs_worker import SqsWorker
from app.models.base import Base
from app.services.event_processor import EventProcessor
from app.utils.logging import configure_logging

logger = logging.getLogger("app.worker")


def main() -> None:
    settings = get_settings()
    configure_logging(settings.service_name + "-worker", settings.environment, settings.log_level)
    if not settings.sqs_queue_url:
        raise SystemExit("SQS_QUEUE_URL is required to run the worker")

    engine = build_engine(settings)
    if settings.auto_create_tables:
        import app.models.notification  # noqa: F401  (registers the table)

        Base.metadata.create_all(engine)
    session_factory = build_session_factory(engine)
    processor = EventProcessor(session_factory, build_deliverer(settings, session_factory))
    worker = SqsWorker(
        boto3.client("sqs", region_name=settings.aws_region),
        settings.sqs_queue_url,
        processor,
        wait_seconds=settings.poll_wait_seconds,
        batch_size=settings.poll_batch_size,
        retry_base=settings.retry_base_delay_seconds,
        retry_cap=settings.retry_max_delay_seconds,
        heartbeat_file=settings.heartbeat_file,
    )

    stop = threading.Event()
    # Kubernetes sends SIGTERM on every deploy: finish the batch in hand, then exit cleanly.
    for sig in (signal.SIGTERM, signal.SIGINT):
        signal.signal(sig, lambda *_: stop.set())
    worker.run(stop)
    engine.dispose()


if __name__ == "__main__":
    main()
