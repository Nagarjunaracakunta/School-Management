import json
import logging
import sys
from datetime import UTC, datetime

from app.utils.request_context import request_id_var

_RESERVED = set(logging.LogRecord("", 0, "", 0, "", (), None).__dict__) | {"message", "asctime"}


class JsonFormatter(logging.Formatter):
    """One JSON object per line: CloudWatch Logs Insights can query these fields directly."""

    def __init__(self, service: str, environment: str) -> None:
        super().__init__()
        self.service = service
        self.environment = environment

    def format(self, record: logging.LogRecord) -> str:
        entry = {
            "timestamp": datetime.fromtimestamp(record.created, UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "service": self.service,
            "environment": self.environment,
            "request_id": request_id_var.get(),
        }
        entry.update({k: v for k, v in record.__dict__.items() if k not in _RESERVED})
        if record.exc_info:
            entry["exception"] = self.formatException(record.exc_info)
        return json.dumps(entry, default=str)


def configure_logging(service: str, environment: str, level: str) -> None:
    handler = logging.StreamHandler(sys.stdout)  # containers log to stdout; the platform ships it
    handler.setFormatter(JsonFormatter(service, environment))
    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(level.upper())
    for noisy in (
        "botocore",
        "boto3",
        "urllib3",
    ):  # their INFO lines ("Found credentials ...") are clutter, not information
        logging.getLogger(noisy).setLevel(logging.WARNING)
    logging.getLogger("uvicorn.access").disabled = True  # we emit our own access log with request_id
