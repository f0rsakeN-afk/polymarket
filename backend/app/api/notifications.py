import logging

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.deps import get_current_user
from app.models.notification import Notification, NotificationPreference
from app.schemas.notification import (
    NotificationPreferenceResponse,
    NotificationResponse,
    UpdateNotificationPreferencesRequest,
)
from app.api.responses import success_response, PaginatedResponse
from app.services.notification_service import NotificationService

logger = logging.getLogger("polymarket")
router = APIRouter(prefix="/notifications", tags=["notifications"])


@router.get("/preferences")
async def get_preferences(
    db: AsyncSession = Depends(get_db),
    current_user = Depends(get_current_user),
):
    prefs = await NotificationService.get_or_create_prefs(db, current_user.id)
    return success_response(NotificationPreferenceResponse(
        email_alerts=prefs.email_alerts,
        email_order_fills=prefs.email_order_fills,
        email_market_resolution=prefs.email_market_resolution,
        email_weekly_digest=prefs.email_weekly_digest,
        push_alerts=prefs.push_alerts,
        push_order_fills=prefs.push_order_fills,
        push_market_resolution=prefs.push_market_resolution,
    ))


@router.put("/preferences")
async def update_preferences(
    req: UpdateNotificationPreferencesRequest,
    db: AsyncSession = Depends(get_db),
    current_user = Depends(get_current_user),
):
    prefs = await NotificationService.get_or_create_prefs(db, current_user.id)
    for field, value in req.model_dump(exclude_none=True).items():
        setattr(prefs, field, value)
    await db.commit()
    return success_response({"message": "Preferences updated"})


@router.get("")
async def list_notifications(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    unread_only: bool = Query(False),
    db: AsyncSession = Depends(get_db),
    current_user = Depends(get_current_user),
):
    query = select(Notification).where(Notification.user_id == current_user.id)
    if unread_only:
        query = query.where(Notification.read_at.is_(None))
    query = query.order_by(Notification.created_at.desc()).offset((page - 1) * page_size).limit(page_size)

    result = await db.execute(query)
    notifications = result.scalars().all()

    count_query = select(Notification).where(Notification.user_id == current_user.id)
    if unread_only:
        count_query = count_query.where(Notification.read_at.is_(None))
    total_result = await db.execute(count_query)
    total = len(total_result.scalars().all())

    return PaginatedResponse(
        data=[
            NotificationResponse(
                id=str(n.id),
                type=n.type,
                title=n.title,
                body=n.body,
                data=n.data,
                read_at=n.read_at,
                created_at=n.created_at,
            )
            for n in notifications
        ],
        total=total,
        page=page,
        page_size=page_size,
        has_more=(page * page_size) < total,
    )


@router.post("/{notification_id}/read")
async def mark_read(
    notification_id: str,
    db: AsyncSession = Depends(get_db),
    current_user = Depends(get_current_user),
):
    ok = await NotificationService.mark_read(db, current_user.id, notification_id)
    if not ok:
        from app.api.exceptions import NotFoundError
        raise NotFoundError("Notification not found")
    return success_response({"message": "Marked as read"})


@router.post("/read-all")
async def mark_all_read(
    db: AsyncSession = Depends(get_db),
    current_user = Depends(get_current_user),
):
    await NotificationService.mark_all_read(db, current_user.id)
    return success_response({"message": "All notifications marked as read"})
