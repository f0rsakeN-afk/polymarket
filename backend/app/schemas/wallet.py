from pydantic import BaseModel, Field


class WalletResponse(BaseModel):
    balance: float
    locked_balance: float
    available_balance: float
    currency: str

    model_config = {"from_attributes": True}


class DepositRequest(BaseModel):
    amount: float = Field(..., gt=0)


class DepositResponse(BaseModel):
    client_secret: str
    amount: float
    currency: str


class WithdrawRequest(BaseModel):
    amount: float = Field(..., gt=0)


class TransactionResponse(BaseModel):
    id: str
    type: str
    amount: float
    balance_after: float
    status: str
    created_at: str

    model_config = {"from_attributes": True}
