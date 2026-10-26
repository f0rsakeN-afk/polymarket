from datetime import datetime
from decimal import Decimal
from typing import Any, TypeVar

from pydantic import BaseModel

T = TypeVar("T")


class ApiResponse[T](BaseModel):
    success: bool = True
    data: T | None = None
    error: str | None = None
    error_code: str | None = None


class PaginatedResponse[T](BaseModel):
    success: bool = True
    data: list[T]
    total: int
    page: int
    page_size: int
    has_more: bool


def success_response(data: Any, message: str | None = None) -> dict:
    resp = {"success": True, "data": data}
    if message:
        resp["message"] = message
    return resp


def _jsonable(value: Any) -> Any:
    """Coerce a detail value into something `json.dumps` will accept.

    Every number in this codebase is a `Decimal` on the way in and out - that is
    correct, and floating point money is not - but `json.dumps` has never heard
    of one. So a `Decimal` left in an error's `details` propagates straight into
    serialisation and raises *inside the error handler*.

    The result is the worst possible failure: the refusal becomes an opaque 500
    with no `error_code` and no explanation. It hits precisely the rejections a
    client most needs to read - `min_shares_out` carried one, so an order that
    failed only because it would have delivered too few shares came back as an
    unexplained server fault instead of the reason it was actually refused.

    Losing the last digit of a diagnostic number is a far better outcome than
    losing the diagnosis, so this coerces rather than rejects.
    """
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, dict):
        return {str(k): _jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_jsonable(v) for v in value]
    if isinstance(value, datetime):
        return value.isoformat()
    return value


def error_response(
    message: str, error_code: str | None = None, details: dict | None = None
) -> dict:
    resp = {"success": False, "error": message}
    if error_code:
        resp["error_code"] = error_code
    if details:
        resp["details"] = _jsonable(details)
    return resp

