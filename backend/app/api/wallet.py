import logging
from decimal import Decimal
from fastapi import APIRouter, Depends, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db, get_db_replica
from app.deps import get_current_user
from app.models.wallet import Wallet, Transaction
from app.schemas.wallet import WalletResponse, DepositResponse, DepositRequest, WithdrawRequest, TransactionResponse
from app.api.responses import success_response
from app.api.exceptions import NotFoundError, ValidationError, InsufficientBalanceError
from app.config import settings

logger = logging.getLogger("polymarket")
router = APIRouter(prefix="/wallet", tags=["wallet"])


@router.get("/", summary="Get wallet balance", description="Get the authenticated user's wallet balance, locked balance, and available balance in USDC.")
async def get_wallet(request: Request, db: AsyncSession = Depends(get_db_replica)):
    user = await get_current_user(request, db)
    result = await db.execute(select(Wallet).where(Wallet.user_id == user.id))
    wallet = result.scalar_one_or_none()
    if not wallet:
        raise NotFoundError("Wallet not found")

    return success_response(WalletResponse(
        balance=float(wallet.balance),
        locked_balance=float(wallet.locked_balance),
        available_balance=float(wallet.balance - wallet.locked_balance),
        currency=wallet.currency,
    ))


@router.post("/deposit", summary="Initiate deposit", description="Create a Stripe PaymentIntent for deposit. Returns client_secret for Stripe Elements frontend.")
async def create_deposit(
    data: DepositRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    user = await get_current_user(request, db)

    if data.amount <= 0:
        raise ValidationError("Amount must be positive")

    # In production: create Stripe PaymentIntent
    # For now, simulate with a mock client_secret
    import uuid
    client_secret = f"pi_{uuid.uuid4().hex}_secret"

    logger.info(f"Deposit initiated: user={user.id} amount={data.amount}")

    return success_response(DepositResponse(
        client_secret=client_secret,
        amount=data.amount,
        currency="USD",
    ))


@router.post("/withdraw", summary="Withdraw funds", description="Request a withdrawal. Deducts from available balance (balance minus locked).")
async def withdraw(
    data: WithdrawRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    user = await get_current_user(request, db)

    if data.amount <= 0:
        raise ValidationError("Amount must be positive")

    result = await db.execute(select(Wallet).where(Wallet.user_id == user.id))
    wallet = result.scalar_one_or_none()
    if not wallet:
        raise NotFoundError("Wallet not found")

    available = wallet.balance - wallet.locked_balance
    if Decimal(str(data.amount)) > available:
        raise InsufficientBalanceError({
            "available": float(available),
            "requested": data.amount,
        })

    # Lock and debit
    wallet.balance -= Decimal(str(data.amount))

    # Record transaction
    tx = Transaction(
        user_id=user.id,
        wallet_id=wallet.id,
        type="withdrawal",
        amount=-Decimal(str(data.amount)),
        balance_after=wallet.balance,
        status="pending",
    )
    db.add(tx)
    await db.commit()

    logger.info(f"Withdrawal: user={user.id} amount={data.amount}")
    return success_response({
        "withdrawal_id": str(tx.id),
        "amount": data.amount,
        "status": "pending",
    })


@router.get("/transactions", summary="List transactions", description="View wallet transaction history with pagination.")
async def list_transactions(
    request: Request,
    page: int = 1,
    page_size: int = 20,
    db: AsyncSession = Depends(get_db_replica),
):
    user = await get_current_user(request, db)

    result = await db.execute(
        select(Transaction)
        .where(Transaction.user_id == user.id)
        .order_by(Transaction.updated_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    txs = result.scalars().all()

    return success_response({
        "transactions": [
            TransactionResponse(
                id=str(tx.id),
                type=tx.type,
                amount=float(tx.amount),
                balance_after=float(tx.balance_after),
                status=tx.status,
                created_at=tx.created_at.isoformat() if tx.created_at else None,
            )
            for tx in txs
        ],
        "page": page,
        "page_size": page_size,
    })
