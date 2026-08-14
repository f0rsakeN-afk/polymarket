import logging
import uuid

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.exceptions import ForbiddenError, NotFoundError, ValidationError
from app.api.responses import PaginatedResponse, success_response
from app.database import get_db
from app.deps import get_current_user
from app.models.audit import AuthAuditEvent
from app.models.user import User
from app.services.audit_service import AuthAuditService
from app.services.liquidity_service import LiquidityService

logger = logging.getLogger("polymarket")
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
    search: str | None = None,
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
    """Ban a user — sets is_active=False."""
    admin = await _get_admin_user(request, db)

    result = await db.execute(select(User).where(User.id == uuid.UUID(user_id)))
    user = result.scalar_one_or_none()
    if not user:
        raise NotFoundError("User not found")

    if user.is_admin:
        raise ForbiddenError("Cannot ban an admin")

    user.is_active = False
    await db.commit()

    ip = request.headers.get("x-forwarded-for", "").split(",")[0].strip() or request.client.host if request.client else None
    ua = request.headers.get("user-agent")
    await AuthAuditService.log_account_banned(db, str(user.id), str(admin.id), ip, ua)

    logger.info(f"User {user.id} banned by admin {admin.id}")
    return success_response({"status": "banned", "user_id": str(user.id)})


@router.patch("/users/{user_id}/unban", summary="Unban user (admin)")
async def unban_user(user_id: str, request: Request, db: AsyncSession = Depends(get_db)):
    """Unban a user — sets is_active=True."""
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
    return success_response({"status": "unbanned", "user_id": str(user.id)})


@router.get("/audit-events", summary="List auth audit events (admin)")
async def list_audit_events(
    request: Request,
    db: AsyncSession = Depends(get_db),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=100),
    event: str | None = None,
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
    return success_response(result)
