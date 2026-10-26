import logging
import uuid
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.exceptions import (
    ForbiddenError,
    NotFoundError,
    UnauthorizedError,
    ValidationError,
)
from app.api.responses import success_response
from app.api.step_up import require_step_up
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
from app.services import admin_audit
from app.services.admin_audit import AdminAuditService
from app.services.cache_service import (
    cache_invalidate_market,
    cache_invalidate_market_lists,
)
from app.services.notification_service import NotificationService
from app.websocket.manager import redis_pubsub

logger = logging.getLogger("PredictX")
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

    # `resolving` counts: the outcome is proposed and settlement is pending •
    # that is exactly the window users must be able to dispute in.
    if market.status not in ("resolving", "resolved", "dispute_window"):
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
    ), message="Dispute filed")


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

    return success_response({"message": "Resolution proposed, dispute window open for 48 hours"}, message="Resolution proposed, dispute window open for 48 hours")


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
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user = Depends(get_current_user),
):
    """Rule on a dispute. Admin only.

    ## Why this needed the same treatment as the other money-moving actions

    An upheld ruling resolves the market and queues settlement: it decides who
    gets paid. That makes it the most consequential privileged action in the
    system, and it had neither step-up nor an audit row - it sat in this router
    rather than `admin.py`, so the sweep that covered the other five never saw it.

    That is a gap in the *guard* as much as in the endpoint. The coverage test
    that claims every privileged action is audited only read `PRIVILEGED_ACTIONS`,
    a list defined in the same module as the actions it claimed to cover - so it
    was structurally incapable of noticing an action elsewhere. That is fixed in
    `test_admin_audit.py`, which now also pins this one.
    """
    if not current_user.is_admin:
        raise ForbiddenError("Only admins can adjudicate disputes")

    # Step-up, same as moving fees to the treasury: an admin session is a bearer
    # token, and a stolen one should not be able to decide who wins real money.
    try:
        await require_step_up(request, current_user, req)
    except (UnauthorizedError, ValidationError) as exc:
        await AdminAuditService.log_action(
            db,
            action=admin_audit.STEP_UP_FAILED,
            actor_id=str(current_user.id),
            actor_email=current_user.email,
            request=request,
            target_type="dispute",
            target_id=str(dispute_id),
            summary="Step-up failed before a dispute ruling",
            success=False,
            failure_reason=str(exc)[:255],
        )
        raise

    if req.ruling not in ("upheld", "dismissed"):
        raise ValidationError("ruling must be 'upheld' or 'dismissed'")

    dispute_id_for_audit = str(dispute_id)
    # Recorded whatever happens next, including a lookup that finds nothing, a
    # refusal, or a crash - a log holding only what went through is a log of what
    # happened to be permitted.
    try:
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
            from app.workers.tasks import (
                resolve_market,  # avoid top-level circular import
            )

            market_result = await db.execute(
                select(Market).where(Market.id == dispute.market_id).with_for_update()
            )
            market = market_result.scalar_one_or_none()
            if market and market.proposed_outcome_id:
                market.status = "resolved"
                market.winning_outcome_id = market.proposed_outcome_id
                market.resolved_at = datetime.now(UTC)

                # Queue settlement BEFORE commit - if the broker is down we fail
                # before the market is marked resolved in the DB, which prevents an
                # orphaned resolution: marked resolved here, paid never.
                # Propagate X-Request-ID for tracing across service boundaries.
                try:
                    request_id = getattr(request, "state", None)
                    request_id = getattr(request_id, "request_id", None) or str(uuid.uuid4())
                    resolve_market.apply_async(
                        args=(str(market.id), str(market.proposed_outcome_id)),
                        task_id=request_id,
                        priority=5,
                    )
                except Exception as e:
                    logger.error(f"Failed to enqueue settlement task for market {market.id}: {e}")
                    raise HTTPException(status_code=503, detail="Settlement service unavailable, please retry")

                await db.commit()

                # The dispute path resolves the market directly rather than going
                # through the admin endpoint, so it needs its own announcement -
                # otherwise a dispute resolution was the one way a market could
                # reach `resolved` with nothing said about it. `settle_market`
                # announces the terminal state once payouts are durable; this is
                # the immediate one.
                try:
                    outcome_row = await db.get(Outcome, market.proposed_outcome_id)
                    await redis_pubsub.publish_market_event(
                        str(market.id),
                        "market:resolved",
                        {
                            "winning_outcome_id": str(market.proposed_outcome_id),
                            "winning_outcome_name": getattr(outcome_row, "name", None),
                            "status": market.status,
                        },
                    )
                except Exception:
                    # The ruling has committed and settlement is queued; failing to
                    # announce it must not fail the adjudication. Logged, not
                    # swallowed - silent non-delivery is what made this invisible.
                    logger.exception(
                        "market:resolved publish failed market=%s after dispute ruling",
                        market.id,
                    )

                await NotificationService.dispatch(
                    db,
                    dispute.user_id,
                    "alert_triggered",
                    "Dispute upheld",
                    f"Your dispute for market {market.slug} has been upheld. The market is now resolved.",
                )

        actual_market_status = market.status if (req.ruling == "upheld" and market) else None

        await AdminAuditService.log_action(
            db,
            action=admin_audit.DISPUTE_ADJICATED,
            actor_id=str(current_user.id),
            actor_email=current_user.email,
            request=request,
            target_type="dispute",
            target_id=str(dispute.id),
            summary=f"Dispute {dispute.id} on market {dispute.market_id} ruled {req.ruling}",
            payload={
                "ruling": req.ruling,
                "market_id": str(dispute.market_id),
                "market_resolved": actual_market_status is not None,
                "winning_outcome_id": (
                    str(market.winning_outcome_id)
                    if market and market.winning_outcome_id
                    else None
                ),
            },
        )

        ruling_msg = "dispute denied" if req.ruling == "dismissed" else "dispute upheld • market resolved"
        return success_response({
            "dispute_id": str(dispute.id),
            "ruling": req.ruling,
            "market_status": actual_market_status,
        }, message=f"Dispute {ruling_msg}")

    except Exception as exc:
        # Recorded as well as successes. A log holding only what went through is a
        # log of what happened to be permitted - and for a ruling that resolves a
        # market and pays out, the attempts that failed are the interesting half.
        #
        # Re-raised rather than swallowed: the audit write must not change whether
        # the adjudication succeeds.
        await AdminAuditService.log_action(
            db,
            action=admin_audit.DISPUTE_ADJICATED,
            actor_id=str(current_user.id),
            actor_email=current_user.email,
            request=request,
            target_type="dispute",
            target_id=dispute_id_for_audit,
            summary=f"Attempted to rule dispute {dispute_id} {getattr(req, 'ruling', '?')}",
            success=False,
            failure_reason=str(exc)[:255],
        )
        raise
