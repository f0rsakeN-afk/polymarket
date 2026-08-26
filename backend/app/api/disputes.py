import logging
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.exceptions import ForbiddenError, NotFoundError, ValidationError
from app.api.responses import success_response
from app.database import get_db
from app.deps import get_current_user
from app.models.dispute import Dispute
from app.models.market import Market, Outcome
from app.models.user import User
from app.schemas.dispute import (
    AdjudicateDisputeRequest,
    CreateDisputeRequest,
    DisputeResponse,
    ProposeResolutionRequest,
)
from app.services.cache_service import (
    cache_invalidate_market,
    cache_invalidate_market_lists,
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
    market_result = await db.execute(
        select(Market).where(Market.id == req.market_id).with_for_update()
    )
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

    # Invalidate market cache so clients see the updated status immediately
    await cache_invalidate_market(str(market.id))
    await cache_invalidate_market_lists()

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

    # Validate that the proposed outcome belongs to this market
    outcome_result = await db.execute(
        select(Outcome).where(Outcome.id == req.outcome_id, Outcome.market_id == req.market_id)
    )
    if not outcome_result.scalar_one_or_none():
        raise ValidationError("Outcome does not belong to this market")

    market.proposed_outcome_id = req.outcome_id
    market.resolution_source = req.resolution_source
    market.resolution_proposed_at = datetime.now(UTC)
    market.dispute_deadline = datetime.now(UTC) + timedelta(hours=DISPUTE_WINDOW_HOURS)
    market.status = "dispute_window"
    await db.commit()

    await cache_invalidate_market(str(market.id))
    await cache_invalidate_market_lists()

    return success_response({"message": "Resolution proposed, dispute window open for 48 hours"})


@router.get("/market/{market_id}")
async def get_disputes_for_market(
    market_id: str,
    page: int = 1,
    page_size: int = Query(default=20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    current_user = Depends(get_current_user),
):
    if not current_user.is_admin:
        raise ForbiddenError("Admin access required to view disputes")
    result = await db.execute(
        select(Dispute, User.username)
        .join(User, Dispute.user_id == User.id)
        .where(Dispute.market_id == market_id)
        .order_by(Dispute.created_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    rows = result.all()
    return success_response([
        {
            "id": str(d.id),
            "market_id": str(d.market_id),
            "user_id": str(d.user_id),
            "username": username,
            "evidence": d.evidence,
            "evidence_url": d.evidence_url,
            "status": d.status,
            "created_at": d.created_at,
        }
        for d, username in rows
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

    result = await db.execute(
        select(Dispute).where(Dispute.id == dispute_id).with_for_update()
    )
    dispute = result.scalar_one_or_none()
    if not dispute:
        raise NotFoundError("Dispute not found")

    if dispute.status != "open":
        raise ValidationError("Dispute is already resolved")

    dispute.status = req.ruling
    await db.commit()

    market = None
    if req.ruling == "upheld":
        from app.workers.tasks import resolve_market  # avoid top-level circular import

        market_result = await db.execute(
            select(Market).where(Market.id == dispute.market_id).with_for_update()
        )
        market = market_result.scalar_one_or_none()
        if market and market.proposed_outcome_id:
            market.status = "resolved"
            market.winning_outcome_id = market.proposed_outcome_id
            market.resolved_at = datetime.now(UTC)

            # Queue settlement BEFORE commit — if broker is down we fail before
            # the market is marked resolved in the DB, preventing orphaned resolution
            try:
                resolve_market.delay(str(market.id), str(market.proposed_outcome_id))
            except Exception as e:
                logger.error(f"Failed to enqueue settlement task for market {market.id}: {e}")
                raise HTTPException(status_code=503, detail="Settlement service unavailable, please retry")

            await db.commit()

            await NotificationService.dispatch(
                db,
                dispute.user_id,
                "alert_triggered",
                "Dispute upheld",
                f"Your dispute for market {market.slug} has been upheld. The market is now resolved.",
            )

    actual_market_status = market.status if (req.ruling == "upheld" and market) else None
    ruling_msg = "dispute denied" if req.ruling == "denied" else "dispute upheld — market resolved"
    return success_response({
        "dispute_id": str(dispute.id),
        "ruling": req.ruling,
        "market_status": actual_market_status,
    }, message=f"Dispute {ruling_msg}")
