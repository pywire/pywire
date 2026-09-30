"""Errors raised by services. The API maps them to status codes, pages to messages."""


class ServiceError(Exception):
    status_code = 400

    def __init__(self, message: str, field: str | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.field = field


class NotAuthenticated(ServiceError):
    status_code = 401


class NotFound(ServiceError):
    """Also used when the caller isn't allowed to know the thing exists."""

    status_code = 404


class Forbidden(ServiceError):
    status_code = 403


class Invalid(ServiceError):
    status_code = 422
