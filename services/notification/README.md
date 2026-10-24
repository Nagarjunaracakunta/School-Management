# Notification Service

Turns events into email/SMS messages, records them, and hands them to SNS. Two processes, one image:

| Process | Command | Role |
|---|---|---|
| API | `uvicorn app.asgi:app --port 8006` | list/read notifications, send a one-off message, retry a failed one |
| Worker | `python -m app.worker` | long-polls SQS for `admission.*`, `payment.completed`, `attendance.absent` events |

```bash
cd services/notification
python3 -m venv .venv && . .venv/bin/activate
pip install -r requirements-dev.txt
cp .env.example .env
pytest                                   # uses moto, an in-process SQS/SNS imitation: no AWS needed
```

Run the whole chain locally with `moto_server -p 5000` (see the Phase 8 write-up for the exact commands).
