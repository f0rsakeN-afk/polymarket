from pydantic import BaseModel

from app.schemas.base import MoneyField, PositiveMoney


class AddLiquidityRequest(BaseModel):
    amount: PositiveMoney
    # Required on a parimutuel (multi-outcome) market, where each outcome has
    # its own pool and liquidity must be attributed to one of them. Ignored on
    # a binary market, which has a single pool.
    outcome: str | None = None


class RemoveLiquidityRequest(BaseModel):
    lp_tokens: PositiveMoney
    outcome: str | None = None


class LiquidityPositionResponse(BaseModel):
    lp_tokens: MoneyField
    collateral_deposited: MoneyField
    pool_lp_token_supply: MoneyField
    pool_yes_shares: MoneyField
    pool_no_shares: MoneyField

    model_config = {"from_attributes": True}
