import logging
from decimal import Decimal

import stripe
from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.exceptions import (
    ForbiddenError,
    NotFoundError,
)
from app.api.responses import success_response
from app.config import settings
from app.database import get_db, get_db_replica
from app.deps import get_current_user
from app.models.wallet import Transaction, Wallet
from app.schemas.wallet import (
    DepositRequest,
    DepositResponse,
    TransactionResponse,
    WalletResponse,
    WithdrawRequest,
)
from app.services.wallet_service import WalletService

logger = logging.getLogger("polymarket")
router = APIRouter(prefix="/wallet", tags=["wallet"])


@router.get("/")
async def get_wallet(request: Request, db: AsyncSession = Depends(get_db_replica)):
    user = await get_current_user(request, db)
    result = await db.execute(select(Wallet).where(Wallet.user_id == user.id))
    wallet = result.scalar_one_or_none()
    if not wallet:
        raise NotFoundError("Wallet not found")
    return success_response(WalletResponse(
        balance=str(wallet.balance),
        locked_balance=str(wallet.locked_balance),
        available_balance=str(wallet.balance - wallet.locked_balance),
        currency=wallet.currency,
    ))


@router.post("/deposit")
async def create_deposit(
    data: DepositRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    user = await get_current_user(request, db)

    if not settings.stripe_secret_key:
        raise NotFoundError("Payment provider not configured")

    stripe.api_key = settings.stripe_secret_key

    intent = stripe.PaymentIntent.create(
        amount=int(data.amount * 100),  # cents
        currency="usdc",  # must match wallet currency exactly
        metadata={"user_id": str(user.id)},
        automatic_payment_methods={"enabled": True},
    )

    logger.info(f"Deposit initiated: user={user.id} amount={data.amount} intent={intent.id}")
    return success_response(DepositResponse(
        client_secret=intent.client_secret,
        payment_intent_id=intent.id,
        amount=data.amount,
        currency="USD",
    ))


@router.post("/withdraw")
async def withdraw(
    data: WithdrawRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    user = await get_current_user(request, db)
    result = await WalletService.withdraw(db, user, Decimal(str(data.amount)), data.idempotency_key)
    return success_response(result, message="Withdrawal submitted")


@router.post("/withdraw/{withdrawal_id}/confirm")
async def confirm_withdrawal(
    withdrawal_id: str,
    request: Request,
    confirmed: bool = True,
    db: AsyncSession = Depends(get_db),
):
    """
    Admin endpoint to confirm or reject a pending withdrawal after blockchain settlement.
    Called by the blockchain watcher service when the on-chain transaction confirms or fails.
    """
    user = await get_current_user(request, db)
    if not user.is_admin:
        raise ForbiddenError("Only admins can confirm withdrawals")

    result = await WalletService.confirm_withdrawal(
        db, withdrawal_id, confirmed=confirmed,
    )
    msg = "Withdrawal confirmed" if confirmed else "Withdrawal rejected"
    return success_response(result, message=msg)


@router.get("/transactions")
async def list_transactions(
    request: Request,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
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
                amount=str(tx.amount),
                balance_after=str(tx.balance_after),
                status=tx.status,
                created_at=tx.created_at.isoformat() if tx.created_at else None,
            )
            for tx in txs
        ],
        "page": page,
        "page_size": page_size,
    })
