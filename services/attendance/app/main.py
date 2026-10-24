import logging
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.api import health
from app.api.v1 import attendance
from app.clients.student_client import HttpStudentClient, StudentClient
from app.config.database import build_engine, build_session_factory
from app.config.settings import Settings, get_settings
from app.models.base import Base
from app.services.outbox_relay import OutboxRelay
from app.utils.errors import AppError
from app.utils.events import EventPublisher, LogPublisher, SqsPublisher
from app.utils.logging import configure_logging
from app.utils.request_context import request_id_var, resolve_request_id

logger = logging.getLogger("app.access")


def _error(status: int, code: str, message: str, details: object | None = None) -> JSONResponse:
    body = {"error": {"code": code, "message": message, "request_id": request_id_var.get(), "details": details}}
    return JSONResponse(status_code=status, content=body)


def create_app(
    settings: Settings | None = None,
    publisher: EventPublisher | None = None,
    student_client: StudentClient | None = None,
) -> FastAPI:
    settings = settings or get_settings()
    configure_logging(settings.service_name, settings.environment, settings.log_level)
    engine = build_engine(settings)
    session_factory = build_session_factory(engine)
    if publisher is None:
        publisher = (
            SqsPublisher(settings.sqs_queue_url, settings.aws_region) if settings.sqs_queue_url else LogPublisher()
        )
    student_client = student_client or HttpStudentClient(settings.student_service_url, settings.student_service_timeout)
    relay = OutboxRelay(session_factory, publisher, settings.outbox_batch_size, settings.outbox_poll_seconds)

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        if settings.auto_create_tables:
            Base.metadata.create_all(engine)
        if settings.outbox_enabled:
            relay.start()
        logger.info("service started", extra={"environment": settings.environment})
        yield
        relay.stop()
        engine.dispose()

    app = FastAPI(title="Attendance Service", version="1.0.0", lifespan=lifespan)
    app.state.settings = settings
    app.state.engine = engine
    app.state.session_factory = session_factory
    app.state.relay = relay
    app.state.student_client = student_client

    @app.middleware("http")
    async def request_context(request: Request, call_next):
        request_id = resolve_request_id(request.headers.get("X-Request-ID"))
        request_id_var.set(request_id)
        start = time.perf_counter()
        try:
            response = await call_next(request)
        except Exception:
            logger.exception("unhandled error", extra={"path": request.url.path})
            response = _error(500, "internal_error", "Something went wrong. Quote the request id to support.")
        response.headers["X-Request-ID"] = request_id
        if request.url.path not in ("/health", "/ready"):  # skip probe noise
            logger.info(
                "request",
                extra={
                    "method": request.method,
                    "path": request.url.path,
                    "status": response.status_code,
                    "duration_ms": round((time.perf_counter() - start) * 1000, 1),
                },
            )
        return response

    @app.exception_handler(AppError)
    async def handle_app_error(_: Request, exc: AppError):
        return _error(exc.status_code, exc.code, exc.message, exc.details)

    @app.exception_handler(StarletteHTTPException)
    async def handle_http_error(_: Request, exc: StarletteHTTPException):
        return _error(exc.status_code, "http_error", str(exc.detail))

    @app.exception_handler(RequestValidationError)
    async def handle_validation(_: Request, exc: RequestValidationError):
        details = [{"field": ".".join(str(p) for p in e["loc"][1:]), "message": e["msg"]} for e in exc.errors()]
        return _error(422, "validation_error", "Request validation failed", details)

    app.include_router(health.router)
    app.include_router(attendance.router)
    return app
