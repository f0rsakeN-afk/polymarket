from pydantic import BaseModel, Field


class AddLiquidityRequest(BaseModel):
    amount: float = Field(..., gt=0)


class RemoveLiquidityRequest(BaseModel):
    lp_tokens: float = Field(..., gt=0)


class LiquidityPositionResponse(BaseModel):
    lp_tokens: float
    collateral_deposited: float
    pool_lp_token_supply: float
    pool_yes_shares: float
    pool_no_shares: float

    model_config = {"from_attributes": True}
