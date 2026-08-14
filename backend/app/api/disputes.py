import logging
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.exceptions import ForbiddenError, NotFoundError, ValidationError
from app.api.responses import success_response
from app.database import get_db
from app.deps import get_current_user
from app.models.dispute import Dispute
from app.models.market import Market
from app.schemas.dispute import (
    AdjudicateDisputeRequest,
    CreateDisputeRequest,
    DisputeResponse,
    ProposeResolutionRequest,
)
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

    if market.dispute_deadline and datetime.now(UTC) > market.dispute_deadline:
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
    market.resolution_proposed_at = datetime.now(UTC)
    market.dispute_deadline = datetime.now(UTC) + timedelta(hours=DISPUTE_WINDOW_HOURS)
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


@router.post("/{dispute_id}/adjudicate")
async def adjudicate_dispute(
    dispute_id: str,
    req: AdjudicateDisputeRequest,
    db: AsyncSession = Depends(get_db),
    current_user = Depends(get_current_user),
):
    if not current_user.is_admin:
        raise ForbiddenError("Only admins can adjudicate disputes")

    if req.ruling not in ("upheld", "dismissed"):
        raise ValidationError("ruling must be 'upheld' or 'dismissed'")

    result = await db.execute(select(Dispute).where(Dispute.id == dispute_id))
    dispute = result.scalar_one_or_none()
    if not dispute:
        raise NotFoundError("Dispute not found")

    if dispute.status != "open":
        raise ValidationError("Dispute is already resolved")

    dispute.status = req.ruling
    await db.commit()

    if req.ruling == "upheld":
        market_result = await db.execute(select(Market).where(Market.id == dispute.market_id))
        market = market_result.scalar_one_or_none()
        if market and market.proposed_outcome_id:
            market.status = "resolved"
            market.winning_outcome_id = market.proposed_outcome_id
            market.resolved_at = datetime.now(UTC)
            await db.commit()

            await NotificationService.dispatch(
                db,
                dispute.user_id,
                "alert_triggered",
                "Dispute upheld",
                f"Your dispute for market {market.slug} has been upheld. The market is now resolved.",
            )

    actual_market_status = market.status if (req.ruling == "upheld" and market) else None
    return success_response({
        "dispute_id": str(dispute.id),
        "ruling": req.ruling,
        "market_status": actual_market_status,
    })
