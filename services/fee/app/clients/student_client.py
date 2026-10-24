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
    def list_classes(self, token: str) -> dict[str, str]: ...


class HttpStudentClient:
    """Asks the Student Service about students. It is the single source of truth for who may see
    which child, so the Fee Service never re-implements parent/teacher ownership rules."""

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

    def get_student(self, student_id: str, token: str) -> dict:
        response = self._get(f"/api/v1/students/{student_id}", token)
        if response.status_code == 200:
            return response.json()
        if response.status_code == 404:  # also what a parent gets for someone else's child
            raise NotFoundError("Student not found")
        self._reject(response)

    def list_student_ids(self, token: str) -> list[str]:
        """IDs of the students the caller may see (for a parent: their own children)."""
        ids: list[str] = []
        for page in range(1, MAX_PAGES + 1):
            response = self._get("/api/v1/students", token, {"page": page, "page_size": 100})
            if response.status_code != 200:
                self._reject(response)
            body = response.json()
            ids.extend(s["id"] for s in body["items"])
            if len(ids) >= body["total"]:
                break
        return ids

    def list_classes(self, token: str) -> dict[str, str]:
        response = self._get("/api/v1/classes", token, {"page_size": 100})
        if response.status_code != 200:
            self._reject(response)
        return {c["id"]: c["name"] for c in response.json()["items"]}

    @staticmethod
    def _reject(response: httpx.Response):
        logger.error(
            "student service rejected request",
            extra={"upstream_status": response.status_code, "upstream_body": response.text[:500]},
        )
        raise UpstreamError(f"The student service rejected the request ({response.status_code}).")
