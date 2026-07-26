import logging
from datetime import datetime, timezone, timedelta

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.deps import get_current_user
from app.models.market import Market
from app.models.dispute import Dispute
from app.schemas.dispute import (
    CreateDisputeRequest,
    DisputeResponse,
    ProposeResolutionRequest,
)
from app.api.responses import success_response
from app.api.exceptions import NotFoundError, ValidationError, ForbiddenError
from app.services.notification_service import NotificationService

logger = logging.getLogger("polymarket")
router = APIRouter(prefix="/disputes", tags=["disputes"])

DISPUTE_WINDOW_HOURS = 48


@router.post("")
async def create_dispute(
    req: CreateDisputeRequest,
    db: AsyncSession = Depends(get_db),
    current_user = Depends(get_current_user),
):
    market_result = await db.execute(select(Market).where(Market.id == req.market_id))
    market = market_result.scalar_one_or_none()
    if not market:
        raise NotFoundError("Market not found")

    if market.status not in ("resolved", "dispute_window"):
        raise ValidationError("Market is not in a resolvable state")

    if market.dispute_deadline and datetime.now(timezone.utc) > market.dispute_deadline:
        raise ValidationError("Dispute window has closed")

    dispute = Dispute(
        market_id=req.market_id,
        user_id=current_user.id,
        evidence=req.evidence,
        evidence_url=req.evidence_url,
    )
    db.add(dispute)
    market.status = "dispute_window"
    await db.commit()
    await db.refresh(dispute)

    await NotificationService.dispatch(
        db,
        current_user.id,
        "alert_triggered",
        "Dispute filed",
        f"Your dispute has been filed for market {market.slug}",
    )

    return success_response(DisputeResponse(
        id=str(dispute.id),
        market_id=str(dispute.market_id),
        user_id=str(dispute.user_id),
        evidence=dispute.evidence,
        evidence_url=dispute.evidence_url,
        status=dispute.status,
        created_at=dispute.created_at,
    ))


@router.post("/propose-resolution")
async def propose_resolution(
    req: ProposeResolutionRequest,
    db: AsyncSession = Depends(get_db),
    current_user = Depends(get_current_user),
):
    if not current_user.is_admin:
        raise ForbiddenError("Only admins can propose resolutions")

    market_result = await db.execute(select(Market).where(Market.id == req.market_id))
    market = market_result.scalar_one_or_none()
    if not market:
        raise NotFoundError("Market not found")

    if market.status != "active":
        raise ValidationError("Market must be active to resolve")

    market.proposed_outcome_id = req.outcome_id
    market.resolution_source = req.resolution_source
    market.resolution_proposed_at = datetime.now(timezone.utc)
    market.dispute_deadline = datetime.now(timezone.utc) + timedelta(hours=DISPUTE_WINDOW_HOURS)
    market.status = "dispute_window"
    await db.commit()

    return success_response({"message": "Resolution proposed, dispute window open for 48 hours"})


@router.get("/market/{market_id}")
async def get_disputes_for_market(
    market_id: str,
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(Dispute).where(Dispute.market_id == market_id).order_by(Dispute.created_at.desc())
    )
    disputes = result.scalars().all()
    return success_response([
        DisputeResponse(
            id=str(d.id),
            market_id=str(d.market_id),
            user_id=str(d.user_id),
            evidence=d.evidence,
            evidence_url=d.evidence_url,
            status=d.status,
            created_at=d.created_at,
        )
        for d in disputes
    ])
