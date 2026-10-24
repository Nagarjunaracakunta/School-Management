"""Queues a reminder for every overdue fee.   python -m app.jobs.overdue_reminders

Runs as a Kubernetes CronJob (every morning). It only WRITES `fee.overdue` events into this service's own outbox table,
inside the same transaction that records the reminder. The API pods' relay then publishes them to the queue, exactly as
it does for payments. So the job needs no queue permission, no call to another service and no login token.

Safe to run twice: a fee reminded within the last REMIND_EVERY_DAYS days is skipped.
"""

import datetime as dt
import logging
import os
import sys

from sqlalchemy.orm import Session, sessionmaker

from app.config.database import build_engine, build_session_factory
from app.config.settings import get_settings
from app.repositories.fee_repository import FeeRepository
from app.schemas.fee import money_str
from app.utils.logging import configure_logging

logger = logging.getLogger("app.jobs.overdue_reminders")
REMIND_EVERY_DAYS = 7
BATCH = 500  # per run, so one bad morning cannot flood the notification system; the next run continues


def queue_overdue_reminders(
    session_factory: sessionmaker[Session],
    *,
    today: dt.date | None = None,
    now: dt.datetime | None = None,
    remind_every_days: int = REMIND_EVERY_DAYS,
    batch: int = BATCH,
) -> int:
    now = now or dt.datetime.now(dt.UTC)
    today = today or now.date()
    with session_factory() as session:
        repo = FeeRepository(session)
        fees = repo.due_for_reminder(today=today, remind_before=now - dt.timedelta(days=remind_every_days), limit=batch)
        for fee in fees:
            repo.add_event(
                "fee.overdue",
                {
                    "fee_id": str(fee.id),
                    "student_id": str(fee.student_id),
                    "student_name": fee.student_name,
                    "fee_name": fee.name,
                    "amount_outstanding": money_str(fee.outstanding),
                    "due_date": fee.due_date.isoformat(),
                    "days_overdue": (today - fee.due_date).days,
                    "parents": fee.parents,
                },
            )
            fee.last_reminded_at = now
        repo.commit()  # reminders and their events are saved together, or not at all
        return len(fees)


def main() -> int:
    settings = get_settings()
    configure_logging(settings.service_name + "-overdue-job", settings.environment, settings.log_level)
    engine = build_engine(settings)
    try:
        count = queue_overdue_reminders(
            build_session_factory(engine),
            remind_every_days=int(os.environ.get("REMIND_EVERY_DAYS", REMIND_EVERY_DAYS)),
            batch=int(os.environ.get("OVERDUE_BATCH", BATCH)),
        )
        logger.info("overdue reminders queued", extra={"count": count})
        return 0
    except Exception:
        logger.exception("overdue reminder job failed")
        return 1
    finally:
        engine.dispose()


if __name__ == "__main__":
    sys.exit(main())
