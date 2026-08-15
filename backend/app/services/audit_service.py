import json
import logging
from typing import Literal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.audit import AuthAuditEvent

logger = logging.getLogger("polymarket")

AuthEvent = Literal[
    "login_success",
    "login_fail",
    "logout",
    "logout_all",
    "register",
    "email_verified",
    "password_change",
    "password_reset_request",
    "password_reset_success",
    "2fa_setup_requested",
    "2fa_enabled",
    "2fa_disabled",
    "account_banned",
    "account_unbanned",
    "suspicious_activity",
]


class AuthAuditService:
    @staticmethod
    async def log(
        db: AsyncSession,
        event: AuthEvent,
        success: bool,
        email: str | None = None,
        user_id: str | None = None,
        ip_address: str | None = None,
        user_agent: str | None = None,
        failure_reason: str | None = None,
        metadata: dict | None = None,
    ):
        """
        Write an audit event. Never raises — failures are logged and swallowed.
        """
        try:
            audit_event = AuthAuditEvent(
                user_id=user_id,
                email=email,
                ip_address=ip_address,
                user_agent=user_agent,
                event=event,
                metadata_=json.dumps(metadata) if metadata else None,
                success="success" if success else "failure",
                failure_reason=failure_reason,
            )
            db.add(audit_event)
            await db.commit()
            logger.info(
                f"AUDIT {event} | success={success} | email={email} | ip={ip_address} | reason={failure_reason}"
            )
        except Exception as e:
            # Never let audit logging failures affect the auth flow
            logger.error(f"Failed to write audit event {event}: {e}")

    @staticmethod
    async def get_events_for_user(
        db: AsyncSession,
        user_id: str,
        page: int = 1,
        page_size: int = 20,
        event_filter: str | None = None,
    ):
        """Get audit events for a specific user (for admin or self-service)."""
        query = select(AuthAuditEvent).where(AuthAuditEvent.user_id == user_id)
        if event_filter:
            query = query.where(AuthAuditEvent.event == event_filter)
        query = query.order_by(AuthAuditEvent.created_at.desc()).offset((page - 1) * page_size).limit(page_size)

        result = await db.execute(query)
        events = result.scalars().all()
        return events

    @staticmethod
    async def get_recent_events(
        db: AsyncSession,
        page: int = 1,
        page_size: int = 50,
        event_filter: str | None = None,
        success_filter: str | None = None,
    ):
        """Get recent audit events across all users (admin only)."""
        query = select(AuthAuditEvent)
        if event_filter:
            query = query.where(AuthAuditEvent.event == event_filter)
        if success_filter in ("success", "failure"):
            query = query.where(AuthAuditEvent.success == success_filter)
        query = query.order_by(AuthAuditEvent.created_at.desc()).offset((page - 1) * page_size).limit(page_size)

        result = await db.execute(query)
        events = result.scalars().all()
        return events

    @staticmethod
    async def log_login_success(db: AsyncSession, email: str, user_id: str, ip: str | None, ua: str | None):
        await AuthAuditService.log(db, "login_success", True, email=email, user_id=user_id, ip_address=ip, user_agent=ua)

    @staticmethod
    async def log_login_fail(
        db: AsyncSession, email: str, ip: str | None, ua: str | None, reason: str
    ):
        await AuthAuditService.log(
            db, "login_fail", False, email=email, ip_address=ip, user_agent=ua, failure_reason=reason
        )

    @staticmethod
    async def log_logout(db: AsyncSession, user_id: str, ip: str | None, ua: str | None):
        await AuthAuditService.log(db, "logout", True, user_id=user_id, ip_address=ip, user_agent=ua)

    @staticmethod
    async def log_logout_all(db: AsyncSession, user_id: str, ip: str | None, ua: str | None):
        await AuthAuditService.log(db, "logout_all", True, user_id=user_id, ip_address=ip, user_agent=ua)

    @staticmethod
    async def log_register(db: AsyncSession, email: str, user_id: str, ip: str | None, ua: str | None):
        await AuthAuditService.log(db, "register", True, email=email, user_id=user_id, ip_address=ip, user_agent=ua)

    @staticmethod
    async def log_email_verified(db: AsyncSession, email: str, user_id: str, ip: str | None, ua: str | None):
        await AuthAuditService.log(db, "email_verified", True, email=email, user_id=user_id, ip_address=ip, user_agent=ua)

    @staticmethod
    async def log_password_change(
        db: AsyncSession, user_id: str, ip: str | None, ua: str | None, success: bool = True, reason: str | None = None
    ):
        await AuthAuditService.log(
            db, "password_change", success, user_id=user_id, ip_address=ip, user_agent=ua, failure_reason=reason
        )

    @staticmethod
    async def log_password_reset_request(
        db: AsyncSession, email: str, ip: str | None, ua: str | None
    ):
        await AuthAuditService.log(
            db, "password_reset_request", True, email=email, ip_address=ip, user_agent=ua
        )

    @staticmethod
    async def log_password_reset_success(
        db: AsyncSession, email: str, user_id: str, ip: str | None, ua: str | None
    ):
        await AuthAuditService.log(
            db, "password_reset_success", True, email=email, user_id=user_id, ip_address=ip, user_agent=ua
        )

    @staticmethod
    async def log_2fa_setup_requested(db: AsyncSession, user_id: str, ip: str | None, ua: str | None):
        await AuthAuditService.log(db, "2fa_setup_requested", True, user_id=user_id, ip_address=ip, user_agent=ua)

    @staticmethod
    async def log_2fa_enabled(db: AsyncSession, user_id: str, ip: str | None, ua: str | None):
        await AuthAuditService.log(db, "2fa_enabled", True, user_id=user_id, ip_address=ip, user_agent=ua)

    @staticmethod
    async def log_2fa_disabled(db: AsyncSession, user_id: str, ip: str | None, ua: str | None):
        await AuthAuditService.log(db, "2fa_disabled", True, user_id=user_id, ip_address=ip, user_agent=ua)

    @staticmethod
    async def log_account_banned(db: AsyncSession, target_user_id: str, admin_user_id: str, ip: str | None, ua: str | None):
        await AuthAuditService.log(
            db, "account_banned", True,
            user_id=target_user_id,
            ip_address=ip,
            user_agent=ua,
            metadata={"admin_user_id": admin_user_id},
        )

    @staticmethod
    async def log_account_unbanned(db: AsyncSession, target_user_id: str, admin_user_id: str, ip: str | None, ua: str | None):
        await AuthAuditService.log(
            db, "account_unbanned", True,
            user_id=target_user_id,
            ip_address=ip,
            user_agent=ua,
            metadata={"admin_user_id": admin_user_id},
        )
