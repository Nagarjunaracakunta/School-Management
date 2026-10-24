class AppError(Exception):
    """Business error that maps cleanly to an HTTP response."""

    status_code = 400
    code = "bad_request"

    def __init__(self, message: str, details: object | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.details = details


class NotFoundError(AppError):
    status_code = 404
    code = "not_found"


class ConflictError(AppError):
    status_code = 409
    code = "conflict"


class ForbiddenError(AppError):
    status_code = 403
    code = "forbidden"


class UpstreamError(AppError):
    """A service we depend on failed. 502 tells the caller 'not your fault, retry later'."""

    status_code = 502
    code = "upstream_error"


class UnauthorizedError(AppError):
    status_code = 401
    code = "unauthorized"
