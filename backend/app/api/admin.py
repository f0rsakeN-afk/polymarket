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
from app.models.dispute import Dispute
from app.models.market import (
    STATUS_ACTIVE,
    STATUS_PENDING_REVIEW,
    STATUS_REJECTED,
    Market,
    Outcome,
)
from app.models.user import RefreshToken, Session, User
from app.schemas.admin import BanRequest, RejectMarketRequest, UnbanRequest
from app.schemas.auth import StepUpRequest
from app.services import admin_audit
from app.services.admin_audit import AdminAuditService
from app.services.audit_service import AuthAuditService
from app.services.cache_service import (
    cache_invalidate_market,
    cache_invalidate_market_lists,
)
from app.services.liquidity_service import LiquidityService
from app.services.notification_service import NotificationService
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
                # So an admin can see why an account is inactive without opening
                # the audit trail. A row that says "banned" and nothing else is
                # the state that gets second-guessed months later.
                "ban_reason": u.ban_reason,
                "banned_at": u.banned_at.isoformat() if u.banned_at else None,
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

    result = await db.execute(select(User).where(User.id == _parse_user_id(user_id)))
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
        # Why the account is inactive, when it is a ban. The detail view is where
        # an admin decides whether to lift it, so the reason belongs here.
        "ban_reason": user.ban_reason,
        "banned_at": user.banned_at.isoformat() if user.banned_at else None,
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
async def ban_user(
    user_id: str,
    data: BanRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Ban a user • deactivates the account and revokes all tokens/sessions.

    The reason is required and is shown to the user. Everything else this does
    — cancelling resting orders, releasing reserved funds, revoking sessions — is
    irreversible from the user's side, so an unexplained ban leaves them unable to
    appeal and the next admin unable to tell a justified one from a mistake.
    """
    admin = await _get_admin_user(request, db)

    result = await db.execute(select(User).where(User.id == _parse_user_id(user_id)))
    user = result.scalar_one_or_none()
    if not user:
        raise NotFoundError("User not found")

    if user.is_admin:
        raise ForbiddenError("Cannot ban an admin")

    user.is_active = False
    user.ban_reason = data.reason.strip()
    user.banned_at = datetime.now(UTC)
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
        summary=f"Banned {user.email}: {user.ban_reason}",
        payload={
            "email": user.email,
            # The reason is the point of this action being answerable, so it goes
            # in the trail as well as the column.
            "reason": user.ban_reason,
            **({"note": data.note} if data.note else {}),
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
async def unban_user(
    user_id: str,
    # Optional body. Every field of `UnbanRequest` is optional, so requiring the
    # body anyway would make `PATCH /unban` fail with a 422 when called with no
    # body at all - a reversal whose note is optional being impossible to perform
    # without inventing something to send.
    data: UnbanRequest | None = None,
    request: Request = None,
    db: AsyncSession = Depends(get_db),
):
    """Unban a user • sets is_active=True.

    Clears the stored reason. An account that still carries a reason it is no
    longer banned for is a support ticket waiting to happen — and on the login
    screen a stale reason would be shown as though it were current. The history is
    not lost: the audit trail holds every ban and unban, with actor, IP and user
    agent.
    """
    admin = await _get_admin_user(request, db)

    result = await db.execute(select(User).where(User.id == _parse_user_id(user_id)))
    user = result.scalar_one_or_none()
    if not user:
        raise NotFoundError("User not found")

    previous_reason = user.ban_reason
    user.is_active = True
    user.ban_reason = None
    user.banned_at = None
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
        summary=(
            f"Unbanned {user.email}"
            + (f": {_note}" if (_note := (data.note.strip() if data and data.note else "")) else "")
        ),
        payload={
            "email": user.email,
            **({"note": _note} if _note else {}),
            # The reason being lifted is part of the record: "what was this
            # account accused of, and why was it dropped?" is one question and
            # the answer spans both rows.
            **({"previous_reason": previous_reason} if previous_reason else {}),
        },
    )

    logger.info(f"User {user.id} unbanned by admin {admin.id}")
    return success_response({"status": "unbanned", "user_id": str(user.id)}, message="User unbanned")


@router.get("/disputes", summary="List disputes for moderation (admin)")
async def list_disputes(
    request: Request,
    db: AsyncSession = Depends(get_db),
    status: str | None = Query("open", max_length=20),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
):
    """The moderation queue for disputes.

    ## Why this had to be added

    Adjudication existed as an endpoint and now has an audit trail and step-up, and
    there was still no way to *find* a dispute to rule on: the only read was
    `GET /disputes/market/{market_id}`, which needs a market id you already have.
    A moderator given "someone disputed X" could not get to the ruling from here.

    Evidence and the market's question come along in the same row. A ruling
    without the claim being disputed is a coin toss with a payout attached, and
    making the moderator open the market first would mean the decision is taken
    away from the evidence.
    """
    admin = await _get_admin_user(request, db)
    _ = admin  # authorisation happens here; the actor is recorded on the ruling

    # `"all"` is a literal, not a status - there is no dispute in that state, so
    # it is a filter for "do not filter". Anything else is matched exactly.
    #
    # The condition is *omitted* rather than passed as `None`, because
    # `Select.where(None)` does not mean "no filter" in SQLAlchemy 2: it compiles
    # to `WHERE NULL`, which is false for every row. An unfiltered queue that
    # silently returns nothing is a moderation queue that looks empty - the worst
    # possible failure, because it looks like a quiet day rather than a broken
    # query. (My first attempt at this filter was the opposite mistake - a
    # conditional expression that read as if `None` were a no-op - and the test
    # asserting that `?status=all` returns ruled disputes is what caught it.)
    condition = None if status in (None, "", "all") else Dispute.status == status

    count_stmt = select(func.count()).select_from(Dispute)
    rows_stmt = (
        select(Dispute, Market)
        .join(Market, Market.id == Dispute.market_id)
        # Oldest first, deliberately: a dispute is waiting on the people holding
        # the money, and the one that has waited longest is costing them the most.
        # Newest-first is what an audit log wants; this is a work queue, and the
        # two want opposite orders.
        .order_by(Dispute.created_at)
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    if condition is not None:
        count_stmt = count_stmt.where(condition)
        rows_stmt = rows_stmt.where(condition)

    total = int(await db.scalar(count_stmt) or 0)
    rows = (await db.execute(rows_stmt)).all()

    from app.models.user import User as _User

    data = []
    for dispute, market in rows:
        proposer = await db.get(_User, dispute.user_id)
        data.append(
            {
                "id": str(dispute.id),
                "market_id": str(dispute.market_id),
                "market_slug": market.slug,
                "market_question": market.question,
                "market_status": market.status,
                "proposed_outcome_id": (
                    str(market.proposed_outcome_id) if market.proposed_outcome_id else None
                ),
                "user_id": str(dispute.user_id),
                "proposer_username": getattr(proposer, "username", None),
                "evidence": dispute.evidence,
                "evidence_url": dispute.evidence_url,
                "status": dispute.status,
                "created_at": dispute.created_at,
            }
        )

    return PaginatedResponse(
        data=data,
        total=total,
        page=page,
        page_size=page_size,
        has_more=(page * page_size) < total,
    )


@router.get("/disputes/{dispute_id}", summary="Get dispute detail (admin)")
async def get_dispute(
    dispute_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """One dispute with its market and proposed outcome.

    Modelled on the market's `resolution_criteria`, which is what an upheld ruling
    is judged against - so the evidence and the criterion can be read side by side
    rather than in two tabs and a memory.
    """
    await _get_admin_user(request, db)

    result = await db.execute(
        select(Dispute, Market)
        .join(Market, Market.id == Dispute.market_id)
        .where(Dispute.id == _parse_dispute_id(dispute_id))
    )
    row = result.one_or_none()
    if not row:
        raise NotFoundError("Dispute not found")
    dispute, market = row

    proposed_name = None
    if market.proposed_outcome_id:
        outcome = await db.get(Outcome, market.proposed_outcome_id)
        proposed_name = getattr(outcome, "name", None)

    return success_response(
        {
            "id": str(dispute.id),
            "market_id": str(dispute.market_id),
            "market_slug": market.slug,
            "market_question": market.question,
            "market_status": market.status,
            "resolution_criteria": market.resolution_criteria,
            "resolution_source": market.resolution_source,
            "proposed_outcome_id": (
                str(market.proposed_outcome_id) if market.proposed_outcome_id else None
            ),
            "proposed_outcome_name": proposed_name,
            "user_id": str(dispute.user_id),
            "evidence": dispute.evidence,
            "evidence_url": dispute.evidence_url,
            "status": dispute.status,
            "created_at": dispute.created_at,
        }
    )


async def _notify_author(
    db: AsyncSession,
    market: Market,
    admin_id,
    ntype: str,
    title: str,
    body: str,
) -> None:
    """Tell a market's author what a moderator decided, and never let that fail.

    ## Why it is wrapped at all

    The action has already happened by the time this runs: the status changed and
    the audit row is written. If the notification then raises — Redis down, the
    notifications table unavailable — an unhandled error would return 500 to a
    moderator who has *already* declined the market. The retry they would
    obviously perform now fails on a second attempt, because the market is no
    longer pending, and the operator is left believing their click did nothing.

    So a courtesy row must never be able to veto the decision it reports on. It is
    logged loudly instead: a moderation queue where nobody is told anything is
    still a working moderation queue, whereas a 500 that reads as "declined" but
    half-applied is not.

    Skipped entirely for an admin's own submission — they just did it, and being
    told is noise that teaches people to ignore the channel.
    """
    if not market.created_by or market.created_by == admin_id:
        return

    try:
        await NotificationService.dispatch(
            db,
            str(market.created_by),
            ntype,
            title,
            body,
            data={
                "market_slug": market.slug,
                "market_id": str(market.id),
            },
        )
    except Exception:
        logger.warning(
            "Could not notify %s about %s (%s). The decision stands; "
            "they can see it under My markets.",
            market.created_by,
            market.slug,
            ntype,
            exc_info=True,
        )


def _parse_user_id(user_id: str):
    """Parse a user id before it reaches the driver.

    `uuid.UUID("not-a-uuid")` raises `ValueError` inside the query, which asyncpg
    surfaces as an unhandled 500 on a *client* mistake — the session is left in a
    failed state and the response says "server error" for something the caller
    typed wrong. `/admin/users/{user_id}/ban` with a bad id did exactly that.

    Same reasoning as `_parse_dispute_id`: a malformed id is a 422, not a crash.
    """
    try:
        return uuid.UUID(user_id)
    except (ValueError, AttributeError, TypeError):
        raise ValidationError("Invalid user id", error_code="INVALID_ID")


def _parse_dispute_id(dispute_id: str):
    """Reject malformed ids as 422 rather than letting asyncpg raise inside a
    session left in a failed state."""
    try:
        return uuid.UUID(dispute_id)
    except (ValueError, AttributeError, TypeError):
        raise ValidationError("Invalid dispute id", error_code="INVALID_ID")


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
                # Carried on the queue row so triage does not need an open per
                # market: "why was this declined?" is the first question asked
                # about every rejected submission in the list.
                "rejection_reason": m.rejection_reason,
                "rejected_at": m.rejected_at.isoformat() if m.rejected_at else None,
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

    # Tell the author, if there is one to tell.
    #
    # Approving is the end of a loop the author started: they proposed something
    # and are waiting to find out whether it is live. Without this they have to
    # go and look — and a market that never went live looks, from the outside,
    # exactly like one that was quietly dropped.
    #
    # Skipped for an admin's own submission, which needs no news.
    await _notify_author(
        db,
        market,
        admin.id,
        "market_submission_reviewed",
        "Your market is live",
        f'"{market.question}" is now open for trading.',
    )

    logger.info(
        "Market approved: %s (%s) by=%s", market.slug, market.id, admin.id
    )
    return success_response(
        {"id": str(market.id), "slug": market.slug, "status": market.status},
        message="Market approved and published",
    )


@router.post("/markets/{market_id}/reject", summary="Reject a submitted market (admin)")
async def reject_market(
    market_id: str,
    data: RejectMarketRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Decline a submission: status → rejected, stays hidden from the catalogue.

    The author keeps read access to their own submission (see GET /markets/{slug}),
    so `rejection_reason` is the only way they learn why. That is why the reason
    is required rather than an optional note: a submission declined with no
    explanation cannot be fixed, because nobody can tell whether the problem was
    the wording, the category, or the resolution criteria.
    """
    admin = await _get_admin_user(request, db)
    market = await _pending_market(db, market_id)

    await _set_market_status(db, market, STATUS_REJECTED)
    market.rejection_reason = data.reason.strip()
    market.rejected_at = datetime.now(UTC)
    await AdminAuditService.log_action(
        db,
        action=admin_audit.MARKET_REJECTED,
        actor_id=str(admin.id),
        actor_email=admin.email,
        request=request,
        target_type="market",
        target_id=str(market.id),
        summary=f"Rejected market {market.slug}: {market.rejection_reason}",
        payload={
            "slug": market.slug,
            "question": market.question,
            "reason": market.rejection_reason,
            **({"note": data.note.strip()} if data.note and data.note.strip() else {}),
        },
    )
    # The reason goes in the notification, not just the column. A decline the
    # author has to go and discover is a decline they may never find — and the
    # whole reason the field is required is that they are entitled to know.
    await _notify_author(
        db,
        market,
        admin.id,
        "market_submission_declined",
        "Your market was declined",
        f'"{market.question}" was not approved: {market.rejection_reason}',
    )

    logger.info(
        "Market rejected: %s (%s) reason=%s",
        market.slug,
        market.id,
        market.rejection_reason,
    )
    return success_response(
        {
            "id": str(market.id),
            "slug": market.slug,
            "status": market.status,
            "rejection_reason": market.rejection_reason,
        },
        message="Market rejected",
    )
