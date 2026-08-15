import logging
from decimal import Decimal

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.exceptions import NotFoundError
from app.api.responses import success_response
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
        balance=float(wallet.balance),
        locked_balance=float(wallet.locked_balance),
        available_balance=float(wallet.balance - wallet.locked_balance),
        currency=wallet.currency,
    ))


@router.post("/deposit")
async def create_deposit(
    data: DepositRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    user = await get_current_user(request, db)
    import uuid
    client_secret = f"pi_{uuid.uuid4().hex}_secret"
    logger.info(f"Deposit initiated: user={user.id} amount={data.amount}")
    return success_response(DepositResponse(
        client_secret=client_secret,
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
    result = await WalletService.withdraw(db, user, Decimal(str(data.amount)))
    return success_response(result)


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
