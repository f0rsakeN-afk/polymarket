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


def error_response(
    message: str, error_code: str | None = None, details: dict | None = None
) -> dict:
    resp = {"success": False, "error": message}
    if error_code:
        resp["error_code"] = error_code
    if details:
        resp["details"] = details
    return resp

