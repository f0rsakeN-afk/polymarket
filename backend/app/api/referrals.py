import logging
import uuid

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.responses import success_response
from app.database import get_db
from app.deps import get_current_user
from app.models.referral import Referral

logger = logging.getLogger("polymarket")
router = APIRouter(prefix="/referrals", tags=["referrals"])


def _generate_code() -> str:
    return str(uuid.uuid4())[:8].upper()


@router.get("/code", summary="Get referral code", description="Get current user's referral code, generating one if missing.")
async def get_referral_code(
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    user = await get_current_user(request, db)

    if not user.referral_code:
        user.referral_code = _generate_code()
        await db.commit()
        await db.refresh(user)

    return success_response({"referral_code": user.referral_code})


@router.get("/stats", summary="Referral stats", description="Get referral statistics for the current user.")
async def get_referral_stats(
    request: Request,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
):
    user = await get_current_user(request, db)

    # Count total referrals
    count_result = await db.execute(
        select(func.count()).select_from(Referral).where(Referral.referrer_id == user.id)
    )
    total = count_result.scalar() or 0

    # Paginated referrals
    result = await db.execute(
        select(Referral)
        .where(Referral.referrer_id == user.id)
        .order_by(Referral.created_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    referrals = result.scalars().all()

    # Aggregate stats across all referrals (not just this page) — single query
    stats_result = await db.execute(
        select(
            func.count().filter(Referral.status == "completed"),
            func.sum(Referral.reward_amount),
        ).where(Referral.referrer_id == user.id)
    )
    row = stats_result.one()
    completed_referrals = row[0] or 0
    total_rewards = float(row[1] or 0)

    return success_response({
        "referral_code": user.referral_code or "",
        "total_referrals": total,
        "completed_referrals": completed_referrals,
        "total_rewards_earned": str(total_rewards),
        "page": page,
        "page_size": page_size,
        "has_more": (page * page_size) < total,
        "referrals": [
            {
                "id": str(r.id),
                "referred_id": str(r.referred_id),
                "status": r.status,
                "reward_amount": str(r.reward_amount),
                "created_at": r.created_at.isoformat(),
                "completed_at": r.completed_at.isoformat() if r.completed_at else None,
            }
            for r in referrals
        ],
    })
