from fastapi import HTTPException


class AppException(HTTPException):
    def __init__(
        self,
        status_code: int,
        message: str,
        error_code: str | None = None,
        details: dict | None = None,
    ):
        self.message = message
        self.error_code = error_code or f"ERR_{status_code}"
        self.details = details or {}
        super().__init__(status_code=status_code, detail={"message": message, "error_code": self.error_code, "details": self.details})


class NotFoundError(AppException):
    def __init__(self, message: str = "Resource not found", details: dict | None = None):
        super().__init__(404, message, "NOT_FOUND", details)


class ConflictError(AppException):
    def __init__(self, message: str = "Resource already exists", details: dict | None = None):
        super().__init__(409, message, "CONFLICT", details)


class UnauthorizedError(AppException):
    def __init__(self, message: str = "Not authenticated", details: dict | None = None):
        super().__init__(401, message, "UNAUTHORIZED", details)


class ForbiddenError(AppException):
    def __init__(self, message: str = "Access denied", details: dict | None = None):
        super().__init__(403, message, "FORBIDDEN", details)


class ValidationError(AppException):
    def __init__(self, message: str = "Validation failed", details: dict | None = None):
        super().__init__(422, message, "VALIDATION_ERROR", details)


class InsufficientBalanceError(AppException):
    def __init__(self, details: dict | None = None):
        super().__init__(400, "Insufficient balance", "INSUFFICIENT_BALANCE", details)


class MarketClosedError(AppException):
    def __init__(self, details: dict | None = None):
        super().__init__(400, "Market is closed for trading", "MARKET_CLOSED", details)


class IdempotencyError(AppException):
    def __init__(self, message: str = "Request already processed", details: dict | None = None):
        super().__init__(409, message, "IDEMPOTENCY_CONFLICT", details)
