import logging

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.exceptions import ForbiddenError, NotFoundError, ValidationError
from app.api.responses import success_response
from app.database import get_db
from app.deps import get_current_user
from app.models.flag import MarketFlag
from app.models.market import Market
from app.schemas.flag import FlagCreateRequest, FlagResponse, ResolveFlagRequest
from app.services.notification_service import NotificationService

logger = logging.getLogger("polymarket")
router = APIRouter(prefix="/flags", tags=["flags"])


@router.post("")
async def flag_market(
    req: FlagCreateRequest,
    db: AsyncSession = Depends(get_db),
    current_user = Depends(get_current_user),
):
    market_result = await db.execute(select(Market).where(Market.id == req.market_id))
    market = market_result.scalar_one_or_none()
    if not market:
        raise NotFoundError("Market not found")

    existing = await db.execute(
        select(MarketFlag)
        .where(MarketFlag.market_id == req.market_id, MarketFlag.user_id == current_user.id)
    )
    if existing.scalar_one_or_none():
        raise ValidationError("You have already flagged this market")

    flag = MarketFlag(
        market_id=req.market_id,
        user_id=current_user.id,
        reason=req.reason,
    )
    db.add(flag)
    await db.commit()
    await db.refresh(flag)

    await NotificationService.dispatch(
        db,
        current_user.id,
        "alert_triggered",
        "Market flagged",
        f"Your flag for market {market.slug} has been recorded.",
    )

    return success_response(FlagResponse(
        id=str(flag.id),
        market_id=str(flag.market_id),
        user_id=str(flag.user_id),
        reason=flag.reason,
        status=flag.status,
        created_at=flag.created_at,
    ))


@router.get("/market/{market_id}")
async def get_market_flags(
    market_id: str,
    db: AsyncSession = Depends(get_db),
    current_user = Depends(get_current_user),
):
    if not current_user.is_admin:
        raise ForbiddenError("Only admins can view flags")

    result = await db.execute(
        select(MarketFlag)
        .where(MarketFlag.market_id == market_id)
        .order_by(MarketFlag.created_at.desc())
    )
    flags = result.scalars().all()
    return success_response([
        FlagResponse(
            id=str(f.id),
            market_id=str(f.market_id),
            user_id=str(f.user_id),
            reason=f.reason,
            status=f.status,
            created_at=f.created_at,
        )
        for f in flags
    ])


@router.patch("/{flag_id}/resolve")
async def resolve_flag(
    flag_id: str,
    req: ResolveFlagRequest,
    db: AsyncSession = Depends(get_db),
    current_user = Depends(get_current_user),
):
    if not current_user.is_admin:
        raise ForbiddenError("Only admins can resolve flags")

    result = await db.execute(select(MarketFlag).where(MarketFlag.id == flag_id))
    flag = result.scalar_one_or_none()
    if not flag:
        raise NotFoundError("Flag not found")

    if flag.status != "open":
        raise ValidationError("Flag is already resolved")

    flag.status = req.status
    await db.commit()

    return success_response({
        "flag_id": str(flag.id),
        "status": req.status,
    })