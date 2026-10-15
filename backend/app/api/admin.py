import logging
import uuid
from datetime import UTC, datetime
from decimal import Decimal

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.exceptions import (
    ConflictError,
    ForbiddenError,
    NotFoundError,
    UnauthorizedError,
    ValidationError,
)
from app.api.responses import PaginatedResponse, success_response
from app.api.step_up import require_step_up
from app.database import get_db
from app.deps import get_current_user
from app.models.audit import AdminAuditEvent, AuthAuditEvent
from app.models.market import (
    STATUS_ACTIVE,
    STATUS_PENDING_REVIEW,
    STATUS_REJECTED,
    Market,
)
from app.models.user import RefreshToken, Session, User
from app.schemas.auth import StepUpRequest
from app.services import admin_audit
from app.services.admin_audit import AdminAuditService
from app.services.audit_service import AuthAuditService
from app.services.cache_service import (
    cache_invalidate_market,
    cache_invalidate_market_lists,
)
from app.services.liquidity_service import LiquidityService
from app.services.order_service import OrderService

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
    """A single user, and enough of their financial record to investigate them.

    ## Why this grew

    This returned profile fields only, so an admin given "this user says they
    lost money" had nothing to look at - while every answer lived in tables that
    were already there. The transaction ledger carries `balance_after` and a
    `reference_id` pointing at the order that caused it, which is exactly what
    makes a balance question answerable.

    Two design points worth stating:

    - **Counts by default, rows on request.** A user with years of trades would
      make an unconditional dump unusable, and an admin rarely needs every row -
      they need the shape first. `?include=trades,positions,transactions` fetches
      the detail, capped and newest-first, because an unbounded response to an
      investigation query is how an endpoint becomes a denial-of-service lever
      an admin can aim at their own server.
    - **Reads are audited.** An admin pulling a user's financial history is a
      privileged action with privacy weight, and it was previously invisible. It
      goes in the same trail as everything else.

    This is a read, so it needs no step-up - there is no irreversible action to
    take. But it is recorded, because "who looked at whose finances" is a
    question an operator has to be able to answer.
    """
    admin = await _get_admin_user(request, db)

    result = await db.execute(select(User).where(User.id == uuid.UUID(user_id)))
    user = result.scalar_one_or_none()
    if not user:
        raise NotFoundError("User not found")

    from app.models.dispute import Dispute
    from app.models.order import Order
    from app.models.position import Position
    from app.models.trade import Trade
    from app.models.wallet import Transaction, Wallet

    include = {
        part.strip() for part in (request.query_params.get("include") or "").split(",") if part.strip()
    }
    detail_limit = min(int(request.query_params.get("limit") or 50), 200)

    async def recent(model, *order_by):
        stmt = select(model).where(model.user_id == user.id)
        for column in order_by:
            stmt = stmt.order_by(column.desc())
        rows = (await db.execute(stmt.limit(detail_limit))).scalars().all()
        return [_serialisable(r) for r in rows]

    wallet = (
        await db.execute(select(Wallet).where(Wallet.user_id == user.id))
    ).scalar_one_or_none()

    async def count(model) -> int:
        return int(
            await db.scalar(select(func.count()).select_from(model).where(model.user_id == user.id))
            or 0
        )

    open_orders = int(
        await db.scalar(
            select(func.count())
            .select_from(Order)
            .where(Order.user_id == user.id, Order.status == "pending")
        )
        or 0
    )

    # Flags an admin acts on, computed rather than left for them to derive. A
    # user whose balances do not reconcile, or who holds funds locked in orders
    # they cannot reach, is a support case before it is a dispute.
    findings: list[str] = []
    if wallet is None:
        findings.append("no_wallet")
    if open_orders:
        findings.append("has_open_orders")
    if wallet and wallet.locked_balance and Decimal(str(wallet.locked_balance)) > 0:
        findings.append("has_locked_funds")
    if user.is_deleted:
        findings.append("account_erased")

    payload = {
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
        "is_deleted": user.is_deleted,
        "wallet": (
            {
                "balance": str(wallet.balance),
                "locked_balance": str(wallet.locked_balance),
                "currency": wallet.currency,
            }
            if wallet
            else None
        ),
        "counts": {
            "orders": await count(Order),
            "open_orders": open_orders,
            "positions": await count(Position),
            "trades": await count(Trade),
            "transactions": await count(Transaction),
            "disputes": await count(Dispute),
        },
        "findings": findings,
    }

    if "trades" in include:
        payload["trades"] = await recent(Trade, Trade.executed_at)
    if "orders" in include:
        payload["orders"] = await recent(Order, Order.created_at)
    if "positions" in include:
        payload["positions"] = await recent(Position, Position.created_at)
    if "transactions" in include:
        payload["transactions"] = await recent(Transaction, Transaction.created_at)

    await AdminAuditService.log_action(
        db,
        action=admin_audit.USER_RECORD_VIEWED,
        actor_id=str(admin.id),
        actor_email=admin.email,
        request=request,
        target_type="user",
        target_id=str(user.id),
        summary=f"Viewed financial record for {user.email}",
        payload={"include": sorted(include), "findings": findings},
    )

    return success_response(payload)


def _serialisable(row) -> dict:
    """Row → plain data, with the types JSON cannot hold converted.

    Decimal as a string, not a float: an admin reconciling a balance against the
    ledger is exactly the person who would be misled by a rounded number, and
    `float()` on money is where that starts.
    """
    out: dict = {}
    for column in row.__table__.columns:
        value = getattr(row, column.name, None)
        if isinstance(value, Decimal):
            value = str(value)
        elif isinstance(value, datetime):
            value = value.isoformat()
        elif isinstance(value, uuid.UUID):
            value = str(value)
        out[column.name] = value
    return out


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
    # Cancel resting orders BEFORE revoking sessions.
    #
    # A ban stops the user trading, so any open order becomes one they can never
    # fill or cancel: their USDC stays reserved against a market they are locked
    # out of, and they are unreachable to tell. Account deletion refuses for
    # exactly this reason - a ban must not create the state deletion guards against.
    #
    # Cancelled here rather than refused-with-409, because a ban is often urgent
    # (fraud, abuse) and a resting order is a reason to act *faster*, not a reason
    # to make an admin wait. The funds are released, not confiscated: the balance
    # is untouched and comes straight back on unban.
    #
    # Each order is cancelled through the ordinary `cancel_order` path, so the
    # fund release and the resulting orderbook push are identical to a
    # user-initiated cancel - every other client's book is stale the moment a
    # resting order vanishes, and that has to be published for each one.
    cancelled_orders = await OrderService.cancel_open_orders_for_user(
        db, user, reason="account_banned"
    )

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
    await AdminAuditService.log_action(
        db,
        action=admin_audit.USER_BANNED,
        actor_id=str(admin.id),
        actor_email=admin.email,
        request=request,
        target_type="user",
        target_id=str(user.id),
        summary=f"Banned {user.email}",
        payload={
            "email": user.email,
            # Named in the audit because it is money: which orders were pulled and
            # the funds released is the first question anyone asks after a ban.
            "cancelled_order_ids": cancelled_orders,
            "cancelled_order_count": len(cancelled_orders),
        },
    )

    logger.info(
        f"User {user.id} banned by admin {admin.id}; "
        f"cancelled {len(cancelled_orders)} open order(s)"
    )
    return success_response(
        {
            "status": "banned",
            "user_id": str(user.id),
            "cancelled_order_ids": cancelled_orders,
        },
        message=f"User banned; {len(cancelled_orders)} open order(s) cancelled",
    )


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
    await AdminAuditService.log_action(
        db,
        action=admin_audit.USER_UNBANNED,
        actor_id=str(admin.id),
        actor_email=admin.email,
        request=request,
        target_type="user",
        target_id=str(user.id),
        summary=f"Unbanned {user.email}",
        payload={"email": user.email},
    )

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


@router.get("/admin-actions", summary="List privileged actions (admin)")
async def list_admin_actions(
    request: Request,
    db: AsyncSession = Depends(get_db),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    actor_id: str | None = Query(None),
    action: str | None = Query(None, max_length=64),
    target_type: str | None = Query(None, max_length=32),
    target_id: str | None = Query(None, max_length=64),
    success: str | None = Query(None),
):
    """The privileged-action trail, filterable by who did it.

    `actor_id` is the filter that was impossible before. The actor used to live
    inside a JSON blob on an auth event, so "show me everything this admin did"
    meant reading every row and parsing every blob - which is why an audit log
    nobody can query is an audit log nobody reads.

    Filtered results report the total that matched, not the page size, so an
    export can page through without silently truncating.
    """
    await _get_admin_user(request, db)

    filters = []
    if actor_id:
        try:
            filters.append(AdminAuditEvent.actor_id == uuid.UUID(actor_id))
        except ValueError:
            raise ValidationError(f"Invalid actor_id format: {actor_id}")
    if action:
        filters.append(AdminAuditEvent.action == action)
    if target_type:
        filters.append(AdminAuditEvent.target_type == target_type)
    if target_id:
        filters.append(AdminAuditEvent.target_id == target_id)
    if success in ("success", "failure"):
        filters.append(AdminAuditEvent.success == success)

    total = (
        await db.execute(select(func.count()).select_from(AdminAuditEvent).where(*filters))
    ).scalar() or 0

    result = await db.execute(
        select(AdminAuditEvent)
        .where(*filters)
        .order_by(AdminAuditEvent.created_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    rows = result.scalars().all()

    return PaginatedResponse(
        data=[
            {
                "id": str(e.id),
                "actor_id": str(e.actor_id) if e.actor_id else None,
                "actor_email": e.actor_email,
                "action": e.action,
                "target_type": e.target_type,
                "target_id": e.target_id,
                "summary": e.summary,
                "payload": e.payload,
                "ip_address": e.ip_address,
                "success": e.success,
                "failure_reason": e.failure_reason,
                "created_at": e.created_at,
            }
            for e in rows
        ],
        total=total,
        page=page,
        page_size=page_size,
        has_more=(page * page_size) < total,
    )


@router.post("/distribute-protocol-fees", summary="Distribute accumulated protocol fees to treasury (admin)")
async def distribute_protocol_fees(
    data: StepUpRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Withdraw protocol fees from all markets to the treasury wallet.

    The one endpoint that moves real money, and until now the one with no record
    of who invoked it - so a disputed treasury balance had nothing to point at.

    Failures are recorded as well as successes. An admin whose attempt is
    rejected is exactly the kind of event worth having in the trail, and a log
    holding only what went through is a log of what happened to be permitted.
    """
    admin = await _get_admin_user(request, db)

    # Step-up failures are audited too: an actor repeatedly guessing at privileged
    # credentials is itself the thing worth a row.
    try:
        await require_step_up(request, admin, data)
    except (UnauthorizedError, ValidationError) as exc:
        await AdminAuditService.log_action(
            db,
            action=admin_audit.STEP_UP_FAILED,
            actor_id=str(admin.id),
            actor_email=admin.email,
            request=request,
            target_type="treasury",
            summary="Step-up failed before a privileged action",
            success=False,
            failure_reason=str(exc)[:255],
        )
        raise

    try:
        result = await LiquidityService.distribute_protocol_fees(db)
    except Exception as exc:
        await AdminAuditService.log_action(
            db,
            action=admin_audit.PROTOCOL_FEES_DISTRIBUTED,
            actor_id=str(admin.id),
            actor_email=admin.email,
            request=request,
            target_type="treasury",
            summary="Protocol fee distribution FAILED",
            success=False,
            failure_reason=f"{type(exc).__name__}: {exc}"[:255],
        )
        raise

    await AdminAuditService.log_action(
        db,
        action=admin_audit.PROTOCOL_FEES_DISTRIBUTED,
        actor_id=str(admin.id),
        actor_email=admin.email,
        request=request,
        target_type="treasury",
        summary="Distributed protocol fees to treasury",
        payload={
            "total_distributed": result.get("total_distributed"),
            "markets_processed": result.get("markets_processed"),
        },
    )
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
    admin = await _get_admin_user(request, db)
    market = await _pending_market(db, market_id)

    # An already-expired submission would go straight into the catalogue dead •
    # it can never be traded, and there is no edit endpoint to fix closes_at.
    if market.closes_at <= datetime.now(UTC):
        raise ValidationError(
            "Market closes_at is in the past • reject it so the author can resubmit",
            error_code="MARKET_ALREADY_CLOSED",
        )

    await _set_market_status(db, market, STATUS_ACTIVE)
    # Approval decides what becomes tradeable. Previously it wrote nothing at all,
    # so the set of live markets could not be attributed to anyone.
    await AdminAuditService.log_action(
        db,
        action=admin_audit.MARKET_APPROVED,
        actor_id=str(admin.id),
        actor_email=admin.email,
        request=request,
        target_type="market",
        target_id=str(market.id),
        summary=f"Approved market {market.slug}",
        payload={"slug": market.slug, "question": market.question},
    )
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
    admin = await _get_admin_user(request, db)
    market = await _pending_market(db, market_id)

    await _set_market_status(db, market, STATUS_REJECTED)
    await AdminAuditService.log_action(
        db,
        action=admin_audit.MARKET_REJECTED,
        actor_id=str(admin.id),
        actor_email=admin.email,
        request=request,
        target_type="market",
        target_id=str(market.id),
        summary=f"Rejected market {market.slug}",
        payload={"slug": market.slug, "question": market.question},
    )
    logger.info(f"Market rejected: {market.slug} ({market.id})")
    return success_response(
        {"id": str(market.id), "slug": market.slug, "status": market.status},
        message="Market rejected",
    )
