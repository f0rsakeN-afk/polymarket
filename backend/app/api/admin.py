import logging
import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.exceptions import (
    ConflictError,
    ForbiddenError,
    NotFoundError,
    ValidationError,
)
from app.api.responses import PaginatedResponse, success_response
from app.database import get_db
from app.deps import get_current_user
from app.models.audit import AuthAuditEvent
from app.models.market import (
    STATUS_ACTIVE,
    STATUS_PENDING_REVIEW,
    STATUS_REJECTED,
    Market,
)
from app.models.user import RefreshToken, Session, User
from app.services.audit_service import AuthAuditService
from app.services.cache_service import (
    cache_invalidate_market,
    cache_invalidate_market_lists,
)
from app.services.liquidity_service import LiquidityService

logger = logging.getLogger("PredictX")
router = APIRouter(prefix="/admin", tags=["admin"])


async def _get_admin_user(request: Request, db: AsyncSession = Depends(get_db)) -> User:
    """Require current user to be admin."""
    user = await get_current_user(request, db)
    if not user.is_admin:
        raise ForbiddenError("Admin access required")
    return user


@router.get("/users", summary="List users (admin)")
async def list_users(
    request: Request,
    db: AsyncSession = Depends(get_db),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    search: str | None = Query(None, max_length=100),
):
    """List all users with pagination and optional search (email or username)."""
    await _get_admin_user(request, db)

    query = select(User)
    count_query = select(func.count(User.id))
    if search:
        # Escape LIKE wildcards to prevent DoS
        safe_search = search.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        query = query.where(
            (User.email.ilike(f"%{safe_search}%", escape="\\")) |
            (User.username.ilike(f"%{safe_search}%", escape="\\"))
        )
        count_query = count_query.where(
            (User.email.ilike(f"%{safe_search}%", escape="\\")) |
            (User.username.ilike(f"%{safe_search}%", escape="\\"))
        )
    query = query.order_by(User.created_at.desc()).offset((page - 1) * page_size).limit(page_size)

    result = await db.execute(query)
    users = result.scalars().all()

    total_result = await db.execute(count_query)
    total = total_result.scalar() or 0

    return PaginatedResponse(
        data=[
            {
                "id": str(u.id),
                "email": u.email,
                "username": u.username,
                "is_active": u.is_active,
                "is_admin": u.is_admin,
                "is_email_verified": u.is_email_verified,
                "is_2fa_enabled": u.is_2fa_enabled,
                "created_at": u.created_at,
            }
            for u in users
        ],
        total=total,
        page=page,
        page_size=page_size,
        has_more=(page * page_size) < total,
    )


@router.get("/users/{user_id}", summary="Get user detail (admin)")
async def get_user(user_id: str, request: Request, db: AsyncSession = Depends(get_db)):
    """Get a single user's details."""
    await _get_admin_user(request, db)

    result = await db.execute(select(User).where(User.id == uuid.UUID(user_id)))
    user = result.scalar_one_or_none()
    if not user:
        raise NotFoundError("User not found")

    return success_response({
        "id": str(user.id),
        "email": user.email,
        "username": user.username,
        "is_active": user.is_active,
        "is_admin": user.is_admin,
        "is_email_verified": user.is_email_verified,
        "is_2fa_enabled": user.is_2fa_enabled,
        "is_2fa_pending": user.is_2fa_pending,
        "referral_code": user.referral_code,
        "created_at": user.created_at,
    })


@router.patch("/users/{user_id}/ban", summary="Ban user (admin)")
async def ban_user(user_id: str, request: Request, db: AsyncSession = Depends(get_db)):
    """Ban a user • deactivates the account and revokes all tokens/sessions."""
    admin = await _get_admin_user(request, db)

    result = await db.execute(select(User).where(User.id == uuid.UUID(user_id)))
    user = result.scalar_one_or_none()
    if not user:
        raise NotFoundError("User not found")

    if user.is_admin:
        raise ForbiddenError("Cannot ban an admin")

    user.is_active = False
    # Revoke all refresh tokens + sessions so the ban takes effect immediately
    # (access JWTs expire naturally within 15 min and are rejected via is_active).
    await db.execute(
        update(RefreshToken)
        .where(RefreshToken.user_id == user.id, RefreshToken.revoked.is_(False))
        .values(revoked=True)
    )
    await db.execute(
        update(Session)
        .where(Session.user_id == user.id, Session.revoked.is_(False))
        .values(revoked=True)
    )
    await db.commit()

    ip = request.headers.get("x-forwarded-for", "").split(",")[0].strip() or request.client.host if request.client else None
    ua = request.headers.get("user-agent")
    await AuthAuditService.log_account_banned(db, str(user.id), str(admin.id), ip, ua)

    logger.info(f"User {user.id} banned by admin {admin.id}")
    return success_response({"status": "banned", "user_id": str(user.id)}, message="User banned")


@router.patch("/users/{user_id}/unban", summary="Unban user (admin)")
async def unban_user(user_id: str, request: Request, db: AsyncSession = Depends(get_db)):
    """Unban a user • sets is_active=True."""
    admin = await _get_admin_user(request, db)

    result = await db.execute(select(User).where(User.id == uuid.UUID(user_id)))
    user = result.scalar_one_or_none()
    if not user:
        raise NotFoundError("User not found")

    user.is_active = True
    await db.commit()

    ip = request.headers.get("x-forwarded-for", "").split(",")[0].strip() or request.client.host if request.client else None
    ua = request.headers.get("user-agent")
    await AuthAuditService.log_account_unbanned(db, str(user.id), str(admin.id), ip, ua)

    logger.info(f"User {user.id} unbanned by admin {admin.id}")
    return success_response({"status": "unbanned", "user_id": str(user.id)}, message="User unbanned")


@router.get("/audit-events", summary="List auth audit events (admin)")
async def list_audit_events(
    request: Request,
    db: AsyncSession = Depends(get_db),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=100),
    event: str | None = Query(None, max_length=64),
    success: str | None = None,
    user_id: str | None = None,
):
    """List auth audit events across all users (admin only)."""
    await _get_admin_user(request, db)

    base_filters = []
    if event:
        base_filters.append(AuthAuditEvent.event == event)
    if success in ("success", "failure"):
        base_filters.append(AuthAuditEvent.success == success)
    if user_id:
        try:
            parsed_uuid = uuid.UUID(user_id)
        except ValueError:
            raise ValidationError(f"Invalid user_id format: {user_id}")
        base_filters.append(AuthAuditEvent.user_id == parsed_uuid)

    count_query = select(func.count(AuthAuditEvent.id)).where(*base_filters)
    total_result = await db.execute(count_query)
    total = total_result.scalar() or 0

    query = select(AuthAuditEvent).where(*base_filters).order_by(
        AuthAuditEvent.created_at.desc()
    ).offset((page - 1) * page_size).limit(page_size)
    result = await db.execute(query)
    events = result.scalars().all()

    return PaginatedResponse(
        data=[
            {
                "id": str(e.id),
                "user_id": str(e.user_id) if e.user_id else None,
                "email": e.email,
                "ip_address": e.ip_address,
                "event": e.event,
                "success": e.success,
                "failure_reason": e.failure_reason,
                "created_at": e.created_at,
            }
            for e in events
        ],
        total=total,
        page=page,
        page_size=page_size,
        has_more=(page * page_size) < total,
    )


@router.post("/distribute-protocol-fees", summary="Distribute accumulated protocol fees to treasury (admin)")
async def distribute_protocol_fees(request: Request, db: AsyncSession = Depends(get_db)):
    """Withdraw protocol fees from all markets to the treasury wallet."""
    await _get_admin_user(request, db)
    result = await LiquidityService.distribute_protocol_fees(db)
    return success_response(result, message="Protocol fees distributed to treasury")


# ─── Market review queue ─────────────────────────────────────────────────────────
# Regular users submit markets (POST /markets/ → status=pending_review); the
# market only enters the public catalogue and becomes tradable once approved.


def _parse_market_id(market_id: str) -> uuid.UUID:
    """Reject malformed ids as 422 instead of letting asyncpg raise inside a
    session that is then left in a failed state."""
    try:
        return uuid.UUID(market_id)
    except (ValueError, AttributeError, TypeError):
        raise ValidationError("Invalid market id", error_code="INVALID_ID")


async def _pending_market(db: AsyncSession, market_id: str) -> Market:
    market = await db.get(Market, _parse_market_id(market_id))
    if market is None:
        raise NotFoundError("Market not found")
    if market.status != STATUS_PENDING_REVIEW:
        raise ValidationError(
            f"Market is '{market.status}', only pending markets can be moderated",
            error_code="MARKET_NOT_PENDING",
        )
    return market


async def _set_market_status(db: AsyncSession, market: Market, new_status: str) -> None:
    """Compare-and-set on the status the moderator actually read.

    Two admins clicking at the same time must not both apply their decision:
    whoever's UPDATE matches 0 rows loses and gets a 409 to re-read.
    """
    result = await db.execute(
        update(Market)
        .where(Market.id == market.id, Market.status == market.status)
        .values(status=new_status)
        .returning(Market.id)
    )
    if result.first() is None:
        await db.rollback()
        raise ConflictError("Market was changed by another request • reload and retry")
    market.status = new_status
    await db.commit()
    # The public list/detail caches would otherwise keep serving the old status.
    await cache_invalidate_market(str(market.id))
    await cache_invalidate_market_lists()


@router.get("/markets", summary="List markets for moderation (admin)")
async def list_markets_admin(
    request: Request,
    db: AsyncSession = Depends(get_db),
    status: str | None = Query(None, max_length=32, description="e.g. pending_review, rejected, active"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
):
    """Every market including ones the public catalogue hides (`status=pending_review`)."""
    await _get_admin_user(request, db)

    filters = [Market.status == status] if status else []
    total = (
        await db.execute(select(func.count(Market.id)).where(*filters))
    ).scalar() or 0

    result = await db.execute(
        select(Market)
        .where(*filters)
        .order_by(Market.created_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    markets = list(result.scalars().all())

    creators: dict = {}
    creator_ids = {m.created_by for m in markets if m.created_by}
    if creator_ids:
        creators_result = await db.execute(select(User).where(User.id.in_(creator_ids)))
        creators = {u.id: u for u in creators_result.scalars().all()}

    return PaginatedResponse(
        data=[
            {
                "id": str(m.id),
                "slug": m.slug,
                "question": m.question,
                "category": m.category,
                "status": m.status,
                "closes_at": m.closes_at,
                "created_at": m.created_at,
                "created_by": str(m.created_by) if m.created_by else None,
                "created_by_email": creators[m.created_by].email if m.created_by in creators else None,
            }
            for m in markets
        ],
        total=total,
        page=page,
        page_size=page_size,
        has_more=(page * page_size) < total,
    )


@router.post("/markets/{market_id}/approve", summary="Approve a submitted market (admin)")
async def approve_market(market_id: str, request: Request, db: AsyncSession = Depends(get_db)):
    """Publish a user-submitted market: status → active, visible and tradable."""
    await _get_admin_user(request, db)
    market = await _pending_market(db, market_id)

    # An already-expired submission would go straight into the catalogue dead •
    # it can never be traded, and there is no edit endpoint to fix closes_at.
    if market.closes_at <= datetime.now(UTC):
        raise ValidationError(
            "Market closes_at is in the past • reject it so the author can resubmit",
            error_code="MARKET_ALREADY_CLOSED",
        )

    await _set_market_status(db, market, STATUS_ACTIVE)
    logger.info(f"Market approved: {market.slug} ({market.id})")
    return success_response(
        {"id": str(market.id), "slug": market.slug, "status": market.status},
        message="Market approved and published",
    )


@router.post("/markets/{market_id}/reject", summary="Reject a submitted market (admin)")
async def reject_market(market_id: str, request: Request, db: AsyncSession = Depends(get_db)):
    """Decline a submission: status → rejected, stays hidden from the catalogue.

    The author keeps read access to their own submission (see GET /markets/{slug}).
    """
    await _get_admin_user(request, db)
    market = await _pending_market(db, market_id)

    await _set_market_status(db, market, STATUS_REJECTED)
    logger.info(f"Market rejected: {market.slug} ({market.id})")
    return success_response(
        {"id": str(market.id), "slug": market.slug, "status": market.status},
        message="Market rejected",
    )
