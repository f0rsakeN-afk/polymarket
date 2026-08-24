
from pydantic import BaseModel, Field

from app.schemas.base import MoneyField, PositiveMoney


class WalletResponse(BaseModel):
    balance: MoneyField
    locked_balance: MoneyField
    available_balance: MoneyField
    currency: str

    model_config = {"from_attributes": True}


class DepositRequest(BaseModel):
    amount: PositiveMoney


class DepositResponse(BaseModel):
    client_secret: str
    payment_intent_id: str
    amount: MoneyField
    currency: str


class WithdrawRequest(BaseModel):
    amount: PositiveMoney
    # Idempotency key — client-generated, prevents double-withdrawal on retry
    idempotency_key: str | None = Field(None, max_length=64)


class TransactionResponse(BaseModel):
    id: str
    type: str
    amount: MoneyField
    balance_after: MoneyField
    status: str
    created_at: str

    model_config = {"from_attributes": True}
