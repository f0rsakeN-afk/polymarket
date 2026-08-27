"""
Shared Pydantic types for the API.
"""
from decimal import Decimal
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
        d = Decimal(str(v)) if not isinstance(v, Decimal) else v
        # Quantize first — don't reject zero here (MoneyField allows 0, only PositiveMoney rejects it)
        return d.quantize(Decimal("0.00000001"))


# ── Shared field helpers ────────────────────────────────────────────────────────

MoneyField = Annotated[Decimal, DecimalField()]
PositiveMoney = Annotated[Decimal, DecimalField(), Gt(0), Le(100_000_000)]
NonNegativeMoney = Annotated[Decimal, DecimalField(), Ge(0), Le(100_000_000)]
PriceMoney = Annotated[Decimal, DecimalField(), Ge(0), Le(1)]
