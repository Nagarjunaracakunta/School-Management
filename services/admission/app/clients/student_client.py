import logging
from typing import Protocol

import httpx

from app.utils.errors import UpstreamError
from app.utils.request_context import request_id_var

logger = logging.getLogger(__name__)


class StudentClient(Protocol):
    def create_student(self, payload: dict, token: str) -> dict: ...


class HttpStudentClient:
    """Synchronous REST call to the Student Service.

    The caller's own JWT is forwarded, so the Student Service applies the same rules it would
    for that user (here: admin only) and logs show who acted. The request id is forwarded too,
    so one id traces the whole chain across both services' logs.
    """

    def __init__(self, base_url: str, timeout: float, transport: httpx.BaseTransport | None = None) -> None:
        # Short timeout: a hung dependency must not hold our threads hostage.
        self._client = httpx.Client(base_url=base_url, timeout=timeout, transport=transport)

    def create_student(self, payload: dict, token: str) -> dict:
        try:
            response = self._client.post(
                "/api/v1/students",
                json=payload,
                headers={"Authorization": f"Bearer {token}", "X-Request-ID": request_id_var.get()},
            )
        except httpx.HTTPError as exc:  # connection refused, DNS failure, timeout...
            logger.exception("student service unreachable")
            raise UpstreamError("The student service is unavailable. Please try again shortly.") from exc
        if response.status_code in (200, 201):  # 200 = this admission was already enrolled earlier
            return response.json()
        logger.error(
            "student service rejected request",
            extra={"upstream_status": response.status_code, "upstream_body": response.text[:500]},
        )
        raise UpstreamError(f"The student service rejected the request ({response.status_code}).")
