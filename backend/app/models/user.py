from datetime import UTC, datetime

from sqlalchemy import Boolean, Column, DateTime, ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from app.models.base import Base, TimestampMixin, UUIDMixin


class User(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "users"

    email = Column(String(255), unique=True, nullable=False, index=True)
    username = Column(String(100), nullable=False, index=True)
    password_hash = Column(String(255), nullable=False)
    is_email_verified = Column(Boolean, default=False, nullable=False)
    is_active = Column(Boolean, default=True, nullable=False)
    is_admin = Column(Boolean, default=False, nullable=False)
    is_system = Column(Boolean, default=False, nullable=False)  # system wallets (treasury)
    referral_code = Column(String(32), unique=True, nullable=True)
    totp_secret_encrypted = Column(String(255), nullable=True)
    is_2fa_enabled = Column(Boolean, default=False, nullable=False)
    is_2fa_pending = Column(Boolean, default=False, nullable=False)  # setup in progress, not confirmed

    # ── Ban ──────────────────────────────────────────────────────────────────
    #
    # Why the account was deactivated, and when.
    #
    # A ban without a stated reason is close to useless: the user cannot appeal
    # what they were not told, and the next admin looking at the account has no
    # way to judge whether the ban was right or a mistake. So the reason is a
    # required field on the request rather than an optional note, and it lives
    # here as well as in the audit trail because it has to be *displayable* —
    # to the user, who is entitled to know, and to an admin opening the record.
    #
    # The **actor** is deliberately not stored here. Two places holding "who
    # banned this" is two places to disagree; the audit trail already records it,
    # with the IP and user agent. This holds only what the record needs to display.
    #
    # Null whenever `is_active` is True. An unban clears both, so "banned" stays a
    # single unambiguous state rather than an account that reads as banned because
    # a stale reason is still attached.
    ban_reason = Column(Text, nullable=True)
    banned_at = Column(DateTime(timezone=True), nullable=True, index=True)

    # ── Erasure ──────────────────────────────────────────────────────────────
    # A deleted account is a tombstone, not a removed row.
    #
    # Almost every table referencing a user cascades on delete, including trades,
    # positions, orders and the transaction ledger. Deleting the row would take
    # the user's trades off the public tape, erase the record of positions they
    # had already settled, and destroy the financial history that the admin
    # audit trail exists to reference. It would also cascade away referral rows
    # that are about *other* people's accounts.
    #
    # So erasure wipes the identity and keeps the ledger: the row survives with
    # every personal attribute replaced, `is_deleted` set, and the trading and
    # financial records left intact but no longer attached to a person.
    #
    # Indexed because "is this address still an account" is now a real question
    # the login and email paths ask.
    is_deleted = Column(Boolean, default=False, nullable=False, index=True)
    deleted_at = Column(DateTime(timezone=True), nullable=True)

    comments = relationship("Comment", back_populates="user")
    referrals_made = relationship("Referral", foreign_keys="Referral.referrer_id", back_populates="referrer")
    referrals_received = relationship("Referral", foreign_keys="Referral.referred_id", back_populates="referred")


class RefreshToken(Base, UUIDMixin):
    __tablename__ = "refresh_tokens"

    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    token_hash = Column(String(255), unique=True, nullable=False)
    expires_at = Column(DateTime(timezone=True), nullable=False)
    revoked = Column(Boolean, default=False, nullable=False, index=True)
    device_info = Column(Text)

    user = relationship("User")
    sessions = relationship("Session", cascade="all, delete-orphan")
    current_session = relationship("Session", back_populates="refresh_token", uselist=False, overlaps="sessions")


class Session(Base, UUIDMixin):
    __tablename__ = "sessions"

    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    refresh_token_id = Column(
        UUID(as_uuid=True), ForeignKey("refresh_tokens.id", ondelete="CASCADE"), nullable=False
    )
    user_agent = Column(Text)
    ip_address = Column(String(45))
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False)
    last_active_at = Column(DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False)
    expires_at = Column(DateTime(timezone=True), nullable=False)
    revoked = Column(Boolean, default=False, nullable=False, index=True)

    user = relationship("User")
    refresh_token = relationship("RefreshToken", back_populates="current_session", overlaps="sessions")
