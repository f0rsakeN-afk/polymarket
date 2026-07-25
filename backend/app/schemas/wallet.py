from pydantic import BaseModel


class WalletResponse(BaseModel):
    balance: float
    locked_balance: float
    available_balance: float
    currency: str

    model_config = {"from_attributes": True}


class DepositRequest(BaseModel):
    amount: float


class DepositResponse(BaseModel):
    client_secret: str
    amount: float
    currency: str


class WithdrawRequest(BaseModel):
    amount: float


class TransactionResponse(BaseModel):
    id: str
    type: str
    amount: float
    balance_after: float
    status: str
    created_at: str

    model_config = {"from_attributes": True}
