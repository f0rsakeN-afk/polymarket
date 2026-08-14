import logging
import uuid

from fastapi import APIRouter, Depends, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.responses import success_response
from app.database import get_db, get_db_replica
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
    db: AsyncSession = Depends(get_db),
):
    user = await get_current_user(request, db)

    made_result = await db.execute(
        select(Referral).where(Referral.referrer_id == user.id)
    )
    referrals = made_result.scalars().all()

    total_referrals = len(referrals)
    completed_referrals = sum(1 for r in referrals if r.status == "completed")
    total_rewards = sum(float(r.reward_amount) for r in referrals)

    return success_response({
        "referral_code": user.referral_code or "",
        "total_referrals": total_referrals,
        "completed_referrals": completed_referrals,
        "total_rewards_earned": total_rewards,
        "referrals": [
            {
                "id": str(r.id),
                "referred_id": str(r.referred_id),
                "status": r.status,
                "reward_amount": float(r.reward_amount),
                "created_at": r.created_at.isoformat(),
                "completed_at": r.completed_at.isoformat() if r.completed_at else None,
            }
            for r in referrals
        ],
    })
