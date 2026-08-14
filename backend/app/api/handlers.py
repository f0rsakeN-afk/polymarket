import logging

from fastapi import HTTPException, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy.exc import IntegrityError

from app.api.exceptions import AppException
from app.api.responses import error_response

logger = logging.getLogger("polymarket")


async def http_exception_handler(request: Request, exc: HTTPException):
    logger.warning(f"HTTP {exc.status_code}: {exc.detail} | path={request.url.path}")
    # Extract message — AppException stores dict in detail, plain HTTPException stores string
    detail = exc.detail
    if isinstance(detail, dict):
        message = detail.get("message", str(detail))
        error_code = detail.get("error_code", f"ERR_{exc.status_code}")
        details = detail.get("details", {})
    else:
        message = str(detail)
        error_code = f"ERR_{exc.status_code}"
        details = {}
    return JSONResponse(
        status_code=exc.status_code,
        content=error_response(message, error_code, details if details else None),
    )


async def app_exception_handler(request: Request, exc: AppException):
    logger.warning(f"{exc.error_code}: {exc.message} | path={request.url.path} details={exc.details}")
    return JSONResponse(
        status_code=exc.status_code,
        content=error_response(exc.message, exc.error_code, exc.details if exc.details else None),
    )


async def validation_exception_handler(request: Request, exc: RequestValidationError):
    errors = []
    for err in exc.errors():
        errors.append({"field": ".".join(str(loc) for loc in err["loc"]), "message": err["msg"]})
    logger.warning(f"Validation error: {errors} | path={request.url.path}")
    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
        content=error_response("Validation failed", "VALIDATION_ERROR", {"errors": errors}),
    )


async def integrity_error_handler(request: Request, exc: IntegrityError):
    logger.error(f"DB integrity error: {exc} | path={request.url.path}")
    return JSONResponse(
        status_code=status.HTTP_409_CONFLICT,
        content=error_response("Resource already exists or constraint violated", "DB_CONSTRAINT_ERROR"),
    )


async def generic_exception_handler(request: Request, exc: Exception):
    logger.exception(f"Unhandled exception: {exc} | path={request.url.path}")
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content=error_response("Internal server error", "INTERNAL_ERROR"),
    )
