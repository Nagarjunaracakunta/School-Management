from pydantic import BaseModel


class Page[T](BaseModel):
    items: list[T]
    total: int
    page: int
    page_size: int


class ErrorBody(BaseModel):
    code: str
    message: str
    request_id: str
    details: object | None = None


class ErrorResponse(BaseModel):
    error: ErrorBody
