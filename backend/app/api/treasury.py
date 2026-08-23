import logging

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.exceptions import ForbiddenError
from app.api.responses import PaginatedResponse, success_response
from app.database import get_db
from app.deps import get_current_user
from app.models.treasury import Treasury, TreasuryLog
from app.models.user import User
from app.schemas.treasury import TreasuryLogResponse, TreasuryResponse

logger = logging.getLogger("polymarket")
router = APIRouter(prefix="/treasury", tags=["treasury"])


async def _get_or_create_treasury(db: AsyncSession) -> Treasury:
    result = await db.execute(select(Treasury))
    treasury = result.scalar_one_or_none()
    if not treasury:
        treasury = Treasury()
        db.add(treasury)
        await db.commit()
        await db.refresh(treasury)
    return treasury


@router.get("")
async def get_treasury(
    db: AsyncSession = Depends(get_db),
):
    treasury = await _get_or_create_treasury(db)
    return success_response(TreasuryResponse(
        id=str(treasury.id),
        balance=str(treasury.balance),
        total_fees_collected=str(treasury.total_fees_collected),
        total_fees_distributed=str(treasury.total_fees_distributed),
    ))


@router.get("/logs")
async def get_treasury_logs(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    event: str | None = Query(None),
    db: AsyncSession = Depends(get_db),
    current_user = Depends(get_current_user),
):
    treasury = await _get_or_create_treasury(db)

    query = select(TreasuryLog).where(TreasuryLog.treasury_id == treasury.id)
    if event:
        query = query.where(TreasuryLog.event == event)
    query = query.order_by(TreasuryLog.created_at.desc()).offset((page - 1) * page_size).limit(page_size)

    result = await db.execute(query)
    logs = result.scalars().all()

    count_query = select(func.count()).select_from(TreasuryLog).where(TreasuryLog.treasury_id == treasury.id)
    if event:
        count_query = count_query.where(TreasuryLog.event == event)
    total_result = await db.execute(count_query)
    total = total_result.scalar() or 0

    return PaginatedResponse(
        data=[
            TreasuryLogResponse(
                id=str(log_entry.id),
                event=log_entry.event,
                amount=str(log_entry.amount),
                reference_type=log_entry.reference_type,
                reference_id=log_entry.reference_id,
                created_at=log_entry.created_at,
            )
            for log_entry in logs
        ],
        total=total,
        page=page,
        page_size=page_size,
        has_more=(page * page_size) < total,
    )


async def _get_admin_user(request: Request, db: AsyncSession = Depends(get_db)) -> User:
    """Require current user to be admin."""
    user = await get_current_user(request, db)
    if not user.is_admin:
        raise ForbiddenError("Admin access required")
    return user


@router.post("/distribute")
async def distribute_fees(
    amount: float = Query(..., gt=0, le=100_000_000, description="Amount to distribute (must be positive, max 100M)"),
    request: Request = None,
    db: AsyncSession = Depends(get_db),
):
    from decimal import Decimal
    await _get_admin_user(request, db)

    treasury = await _get_or_create_treasury(db)
    amount_dec = Decimal(str(amount))
    if treasury.balance < amount_dec:
        from app.api.exceptions import ValidationError
        raise ValidationError("Insufficient treasury balance")

    treasury.balance -= amount_dec
    treasury.total_fees_distributed += amount_dec

    log = TreasuryLog(
        treasury_id=treasury.id,
        event="distribution",
        amount=amount_dec,
        reference_type="manual",
    )
    db.add(log)
    await db.commit()

    return success_response({"message": f"Distributed {amount} from treasury"})
