from decimal import Decimal

from pydantic import BaseModel

from app.schemas.base import MoneyField, NonNegativeMoney, PositiveMoney


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
    amount: MoneyField
    currency: str


class WithdrawRequest(BaseModel):
    amount: PositiveMoney


class TransactionResponse(BaseModel):
    id: str
    type: str
    amount: MoneyField
    balance_after: MoneyField
    status: str
    created_at: str

    model_config = {"from_attributes": True}
