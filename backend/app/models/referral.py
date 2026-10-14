from decimal import Decimal

from sqlalchemy import CheckConstraint, Column, DateTime, ForeignKey, Numeric, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from app.models.base import Base, TimestampMixin, UUIDMixin


class Referral(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "referrals"
    __table_args__ = (
        # A referral must name at least one party.
        #
        # Both FKs below are SET NULL, so an orphaned row is a legitimate state -
        # it is the historical record after one side has gone. A row naming
        # *neither* side is not a record of anything, and permitting one would
        # let a future INSERT quietly fabricate referrals that no aggregate could
        # ever explain.
        CheckConstraint(
            "referrer_id IS NOT NULL OR referred_id IS NOT NULL",
            name="ck_referrals_at_least_one_party",
        ),
    )

    # Both sides are SET NULL, and that is not because these two columns are
    # interchangeable. It is that *no* row may be destroyed by a participant
    # leaving:
    #
    #   referred_id null  the referred user left. Their entitlement is theirs to
    #                     lose, but `reward_amount` is the referrer's *already
    #                     paid* earnings - money that left a wallet, so the record
    #                     of it has to outlive both people.
    #   referrer_id null  the referrer left. Their referral list is theirs, but a
    #                     row still `pending` is a reward the referred user is
    #                     owed.
    #
    # The second case is why `CASCADE` belongs on neither column: it is not a
    # privacy question, it is money owed to someone who is still here. Cascading
    # the referrer away would confiscate a pending reward from a user who did
    # nothing wrong.
    #
    # Nothing hard-deletes a user today - erasure anonymises - so this is a guard
    # on the schema rather than a live bug. Which is the point: "right to be
    # forgotten" is a reasonable thing for a future engineer, or a regulator, to
    # assume already works - and a cascade would have quietly destroyed a rewards
    # ledger the day someone added one.
    referrer_id = Column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    referred_id = Column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    referral_code = Column(String(32), nullable=False, index=True)
    status = Column(String(20), default="pending")
    reward_amount = Column(Numeric(20, 8), default=Decimal(0))
    # `Column(DateTime(timezone=True), nullable=True)`, not
    # `Column(DateTime, timezone=True), nullable=True` - the latter is a tuple
    # assignment, so the attribute is a `(Column, True)` pair rather than a
    # column. It happened to map anyway, which is exactly why it was worth
    # replacing rather than leaving: a declaration that works by accident is one
    # refactor away from not working at all.
    completed_at = Column(DateTime(timezone=True), nullable=True)

    referrer = relationship("User", foreign_keys=[referrer_id], back_populates="referrals_made")
    referred = relationship("User", foreign_keys=[referred_id], back_populates="referrals_received")