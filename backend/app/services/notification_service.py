import logging
from datetime import datetime, timezone
from typing import Literal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.notification import Notification, NotificationPreference
from app.models.user import User
from app.redis import get_redis, redis_cb

logger = logging.getLogger("polymarket")

NotificationType = Literal[
    "alert_triggered",
    "order_filled",
    "order_cancelled",
    "market_resolved",
    "market_closing_soon",
    "weekly_digest",
]


class NotificationService:

    @staticmethod
    async def get_or_create_prefs(db: AsyncSession, user_id: str) -> NotificationPreference:
        result = await db.execute(
            select(NotificationPreference).where(NotificationPreference.user_id == user_id)
        )
        prefs = result.scalar_one_or_none()
        if not prefs:
            prefs = NotificationPreference(user_id=user_id)
            db.add(prefs)
            await db.commit()
            await db.refresh(prefs)
        return prefs

    @staticmethod
    async def create_in_app(
        db: AsyncSession,
        user_id: str,
        ntype: NotificationType,
        title: str,
        body: str | None = None,
        data: dict | None = None,
    ) -> Notification:
        notif = Notification(
            user_id=user_id,
            type=ntype,
            title=title,
            body=body,
            data=data or {},
            channel="in_app",
        )
        db.add(notif)
        await db.commit()
        await db.refresh(notif)
        return notif

    @staticmethod
    async def dispatch(
        db: AsyncSession,
        user_id: str,
        ntype: NotificationType,
        title: str,
        body: str | None = None,
        data: dict | None = None,
    ) -> None:
        await NotificationService.create_in_app(db, user_id, ntype, title, body, data)

        prefs = await NotificationService.get_or_create_prefs(db, user_id)
        user_result = await db.execute(select(User).where(User.id == user_id))
        user = user_result.scalar_one_or_none()
        if not user:
            return

        should_email = False
        if ntype == "alert_triggered" and prefs.email_alerts:
            should_email = True
        elif ntype == "order_filled" and prefs.email_order_fills:
            should_email = True
        elif ntype == "market_resolved" and prefs.email_market_resolution:
            should_email = True

        if should_email and user.email and settings.resend_api_key:
            try:
                from app.workers.tasks import send_email
                send_email.delay(user.email, title, body or title)
            except Exception:
                pass

    @staticmethod
    async def mark_read(db: AsyncSession, user_id: str, notification_id: str) -> bool:
        result = await db.execute(
            select(Notification).where(
                Notification.id == notification_id,
                Notification.user_id == user_id,
            )
        )
        notif = result.scalar_one_or_none()
        if not notif:
            return False
        notif.read_at = datetime.now(timezone.utc)
        await db.commit()
        return True

    @staticmethod
    async def mark_all_read(db: AsyncSession, user_id: str) -> None:
        from sqlalchemy import update
        await db.execute(
            update(Notification).where(
                Notification.user_id == user_id,
                Notification.read_at.is_(None),
            ).values(read_at=datetime.now(timezone.utc))
        )
        await db.commit()
