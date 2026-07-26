import logging

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.deps import get_current_user
from app.models.treasury import Treasury, TreasuryLog
from app.schemas.treasury import TreasuryResponse, TreasuryLogResponse
from app.api.responses import success_response, PaginatedResponse
from app.api.exceptions import ForbiddenError

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
        balance=float(treasury.balance),
        total_fees_collected=float(treasury.total_fees_collected),
        total_fees_distributed=float(treasury.total_fees_distributed),
    ))


@router.get("/logs")
async def get_treasury_logs(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    event: str | None = Query(None),
    db: AsyncSession = Depends(get_db),
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
                id=str(l.id),
                event=l.event,
                amount=float(l.amount),
                reference_type=l.reference_type,
                reference_id=l.reference_id,
                created_at=l.created_at,
            )
            for l in logs
        ],
        total=total,
        page=page,
        page_size=page_size,
        has_more=(page * page_size) < total,
    )


@router.post("/distribute")
async def distribute_fees(
    amount: float,
    db: AsyncSession = Depends(get_db),
    current_user = Depends(get_current_user),
):
    if not current_user.is_admin:
        raise ForbiddenError("Only admins can distribute fees")

    treasury = await _get_or_create_treasury(db)
    if treasury.balance < amount:
        from app.api.exceptions import ValidationError
        raise ValidationError("Insufficient treasury balance")

    treasury.balance -= amount
    treasury.total_fees_distributed += amount

    log = TreasuryLog(
        treasury_id=treasury.id,
        event="distribution",
        amount=amount,
        reference_type="manual",
    )
    db.add(log)
    await db.commit()

    return success_response({"message": f"Distributed {amount} from treasury"})
