from pydantic import BaseModel, Field

from app.schemas.base import MoneyField, NonNegativeMoney, PositiveMoney


class AddLiquidityRequest(BaseModel):
    amount: PositiveMoney


class RemoveLiquidityRequest(BaseModel):
    lp_tokens: PositiveMoney


class LiquidityPositionResponse(BaseModel):
    lp_tokens: MoneyField
    collateral_deposited: MoneyField
    pool_lp_token_supply: MoneyField
    pool_yes_shares: MoneyField
    pool_no_shares: MoneyField

    model_config = {"from_attributes": True}
