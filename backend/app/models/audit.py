
from sqlalchemy import Column, ForeignKey, Index, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
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


class AdminAuditEvent(Base, UUIDMixin, TimestampMixin):
    """
    Immutable audit log of privileged actions.

    Separate from `AuthAuditEvent` on purpose. That table records what happened to
    *an account* - logins, password changes, 2FA. This one records what an *actor
    did*, which is a different question with a different shape.

    The distinction is not tidiness. `AuthAuditEvent` had exactly one place an
    admin appeared: inside a JSON blob under `metadata`. That made the question an
    auditor actually asks - "show me everything this admin did" - unanswerable,
    because the actor could not be indexed or filtered on and every row would have
    to be read. So the actor is a first-class column here, with an index on it.

    And it exists because the most consequential actions in the application wrote
    nothing at all. `distribute-protocol-fees` moves accumulated protocol fees to
    the treasury; market approval decides what is tradeable. Both were reachable
    by any authenticated admin with no record of who invoked them, which is the
    one property an audit log exists to provide.

    Rows are append-only. There is no update path and no delete path on purpose:
    an audit trail an operator can quietly edit is not a trail.
    """

    __tablename__ = "admin_audit_events"

    # Who did it. SET NULL rather than CASCADE: deleting an admin must not delete
    # the record that they once existed and once acted.
    actor_id = Column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    # Denormalised so the trail survives the actor's account being deleted, and so
    # a row is readable without a join to a user who may no longer be there.
    actor_email = Column(String(255), nullable=True)

    # market_approved | market_rejected | user_banned | user_unbanned
    # protocol_fees_distributed | ...
    action = Column(String(64), nullable=False, index=True)

    # What was acted on. Kept as loose type + id rather than a polymorphic FK,
    # because the targets are unrelated tables and a nullable FK per type would be
    # five mostly-null columns.
    target_type = Column(String(32), nullable=True, index=True)
    target_id = Column(String(64), nullable=True, index=True)

    # One line a human can read without decoding the payload. The payload is for
    # machines; this is for whoever opens the log at 3am.
    summary = Column(Text, nullable=True)

    # JSONB rather than a JSON string: audit questions are frequently "anything
    # touching market X" or "any distribution over $N", and an unindexable string
    # cannot answer either without reading every row.
    payload = Column(JSONB, default=dict)

    ip_address = Column(String(45), nullable=True, index=True)
    user_agent = Column(Text, nullable=True)

    # A rejected privileged action is recorded too. "Admin X tried to ban the
    # treasury" is exactly the kind of thing worth knowing, and it is invisible if
    # only successes are logged.
    success = Column(String(10), nullable=False, default="success")
    failure_reason = Column(String(255), nullable=True)

    __table_args__ = (
        # The two access patterns that matter: this actor's trail, and one kind of
        # action over time.
        Index("ix_admin_audit_actor_created", "actor_id", "created_at"),
        Index("ix_admin_audit_action_created", "action", "created_at"),
        Index("ix_admin_audit_target", "target_type", "target_id"),
    )

    actor = relationship("User", foreign_keys=[actor_id])
