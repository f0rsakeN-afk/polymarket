"""
Shared Pydantic types for the API.
"""
from decimal import Decimal, InvalidOperation
from typing import Annotated

from annotated_types import Ge, Gt, Le
from pydantic import GetJsonSchemaHandler
from pydantic_core import CoreSchema, core_schema


def _decimal_to_str(v: Decimal) -> str:
    return str(v)


class DecimalField:
    """A Pydantic field type that properly handles Decimal with fixed 8 decimal precision.

    Use this for all money/amount fields to avoid float precision issues.
    Serializes to string in JSON (preserves precision), accepts str/float/int in input.
    """

    @classmethod
    def __get_pydantic_core_schema__(
        cls, source_type: any, handler: GetJsonSchemaHandler
    ) -> CoreSchema:
        return core_schema.with_info_plain_validator_function(
            cls._validate,
            serialization=core_schema.plain_serializer_function_ser_schema(
                function=_decimal_to_str,
                return_schema=core_schema.str_schema(),
                info_arg=False,
            ),
        )

    @classmethod
    def _validate(cls, v: any, info: any = None) -> Decimal:
        # Decimal(str(x)) raises decimal.InvalidOperation on junk input
        # ("abc") and on absurd exponents ("1e999999999"). InvalidOperation
        # is an ArithmeticError, which Pydantic does NOT convert into a
        # ValidationError — it would escape as an unhandled exception and
        # surface as HTTP 500 instead of a 422. Raise ValueError instead:
        # pydantic-core turns that into a proper field-level ValidationError.
        try:
            d = Decimal(str(v)) if not isinstance(v, Decimal) else v
        except (InvalidOperation, ValueError, TypeError, ArithmeticError):
            raise ValueError(f"Invalid decimal value: {str(v)[:64]!r}")
        if not d.is_finite():
            raise ValueError("Value must be a finite number")
        # Quantize first — don't reject zero here (MoneyField allows 0, only PositiveMoney rejects it)
        try:
            return d.quantize(Decimal("0.00000001"))
        except InvalidOperation:
            # More than 8 decimal places / too many significant digits for
            # the default decimal context — reject instead of 500ing.
            raise ValueError("Value has too many decimal places or is out of range")


# ── Shared field helpers ────────────────────────────────────────────────────────

MoneyField = Annotated[Decimal, DecimalField()]
PositiveMoney = Annotated[Decimal, DecimalField(), Gt(0), Le(100_000_000)]
NonNegativeMoney = Annotated[Decimal, DecimalField(), Ge(0), Le(100_000_000)]
PriceMoney = Annotated[Decimal, DecimalField(), Ge(0), Le(1)]
