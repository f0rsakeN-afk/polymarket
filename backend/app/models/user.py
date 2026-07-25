import uuid
from datetime import datetime, timezone
from sqlalchemy import Column, String, DateTime, Boolean, ForeignKey, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from app.models.base import Base, UUIDMixin, TimestampMixin


class User(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "users"

    email = Column(String(255), unique=True, nullable=False, index=True)
    username = Column(String(100), unique=True, nullable=False, index=True)
    password_hash = Column(String(255), nullable=False)
    is_verified = Column(Boolean, default=False, nullable=False)
    is_active = Column(Boolean, default=True, nullable=False)
    is_admin = Column(Boolean, default=False, nullable=False)
    is_system = Column(Boolean, default=False, nullable=False)  # system wallets (treasury)
    referral_code = Column(String(32), unique=True, nullable=True)

    comments = relationship("Comment", back_populates="user")
    referrals_made = relationship("Referral", foreign_keys="Referral.referrer_id", back_populates="referrer")
    referrals_received = relationship("Referral", foreign_keys="Referral.referred_id", back_populates="referred")


class RefreshToken(Base, UUIDMixin):
    __tablename__ = "refresh_tokens"

    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    token_hash = Column(String(255), unique=True, nullable=False)
    expires_at = Column(DateTime(timezone=True), nullable=False)
    revoked = Column(Boolean, default=False, nullable=False)
    device_info = Column(Text)

    user = relationship("User")
    sessions = relationship("Session", cascade="all, delete-orphan")


class Session(Base, UUIDMixin):
    __tablename__ = "sessions"

    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    refresh_token_id = Column(
        UUID(as_uuid=True), ForeignKey("refresh_tokens.id", ondelete="CASCADE"), nullable=False
    )
    user_agent = Column(Text)
    ip_address = Column(String(45))
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)
    last_active_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)
    expires_at = Column(DateTime(timezone=True), nullable=False)

    user = relationship("User")
    refresh_token = relationship("RefreshToken", back_populates="sessions")
