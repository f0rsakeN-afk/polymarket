from datetime import UTC, datetime

from sqlalchemy import Column, DateTime, ForeignKey, Index, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from app.models.base import Base, TimestampMixin, UUIDMixin


class AuthAuditEvent(Base, UUIDMixin, TimestampMixin):
    """
    Immutable audit log of authentication events.
    Used for forensics, anomaly detection, and compliance.
    """
    __tablename__ = "auth_audit_events"

    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    # If user is None, event is anonymous (e.g. failed login attempt on unknown email)
    email = Column(String(255), nullable=True, index=True)
    ip_address = Column(String(45), nullable=True, index=True)
    user_agent = Column(Text, nullable=True)

    event = Column(String(64), nullable=False, index=True)
    # login_success | login_fail | logout | register | email_verified
    # password_change | password_reset_request | password_reset_success
    # 2fa_enabled | 2fa_disabled | 2fa_setup_requested
    # account_banned | account_unbanned | account_locked
    # suspicious_activity

    metadata_ = Column("metadata", Text, nullable=True)  # JSON string for extra context

    success = Column(String(10), nullable=False)  # "success" | "failure"
    failure_reason = Column(String(128), nullable=True)

    # Derived for analytics
    __table_args__ = (
        Index("ix_auth_audit_user_event", "user_id", "event"),
        Index("ix_auth_audit_email_event", "email", "event"),
        Index("ix_auth_audit_created_at", "created_at"),
    )

    user = relationship("User")
