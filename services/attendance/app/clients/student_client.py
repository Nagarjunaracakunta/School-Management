import logging
from typing import Protocol

import httpx

from app.utils.errors import NotFoundError, UpstreamError
from app.utils.request_context import request_id_var

logger = logging.getLogger(__name__)
MAX_PAGES = 10  # safety cap when walking a paged list


class StudentClient(Protocol):
    def get_student(self, student_id: str, token: str) -> dict: ...
    def list_student_ids(self, token: str) -> list[str]: ...
    def list_section_students(self, section_id: str, token: str) -> list[dict]: ...
    def list_teachers(self, token: str) -> list[dict]: ...


class HttpStudentClient:
    """Asks the Student Service about students and teachers.

    It decides what the CALLER may see (a teacher only gets students of sections they teach), so
    this service never re-implements those rules: whatever comes back is what the caller may act on.
    """

    def __init__(self, base_url: str, timeout: float, transport: httpx.BaseTransport | None = None) -> None:
        self._client = httpx.Client(base_url=base_url, timeout=timeout, transport=transport)

    def _get(self, path: str, token: str, params: dict | None = None) -> httpx.Response:
        try:
            return self._client.get(
                path,
                params=params,
                headers={"Authorization": f"Bearer {token}", "X-Request-ID": request_id_var.get()},
            )
        except httpx.HTTPError as exc:
            logger.exception("student service unreachable")
            raise UpstreamError("The student service is unavailable. Please try again shortly.") from exc

    def _all_pages(self, path: str, token: str, params: dict | None = None) -> list[dict]:
        items: list[dict] = []
        for page in range(1, MAX_PAGES + 1):
            response = self._get(path, token, {**(params or {}), "page": page, "page_size": 100})
            if response.status_code != 200:
                self._reject(response)
            body = response.json()
            items.extend(body["items"])
            if len(items) >= body["total"]:
                break
        return items

    def get_student(self, student_id: str, token: str) -> dict:
        response = self._get(f"/api/v1/students/{student_id}", token)
        if response.status_code == 200:
            return response.json()
        if response.status_code == 404:  # also what a parent/teacher gets for a student they may not see
            raise NotFoundError("Student not found")
        self._reject(response)

    def list_student_ids(self, token: str) -> list[str]:
        return [s["id"] for s in self._all_pages("/api/v1/students", token)]

    def list_section_students(self, section_id: str, token: str) -> list[dict]:
        return self._all_pages("/api/v1/students", token, {"section_id": section_id, "status": "ACTIVE"})

    def list_teachers(self, token: str) -> list[dict]:
        return self._all_pages("/api/v1/teachers", token)

    @staticmethod
    def _reject(response: httpx.Response):
        logger.error(
            "student service rejected request",
            extra={"upstream_status": response.status_code, "upstream_body": response.text[:500]},
        )
        raise UpstreamError(f"The student service rejected the request ({response.status_code}).")
