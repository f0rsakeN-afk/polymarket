from app.models.base import Base, UUIDMixin, TimestampMixin
from sqlalchemy import Column, String, Numeric, ForeignKey, CheckConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship


class Treasury(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "treasury"
    __table_args__ = (CheckConstraint("balance >= 0"),)

    balance = Column(Numeric(20, 8), default=0, nullable=False)
    total_fees_collected = Column(Numeric(20, 8), default=0, nullable=False)
    total_fees_distributed = Column(Numeric(20, 8), default=0, nullable=False)


class TreasuryLog(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "treasury_logs"

    treasury_id = Column(UUID(as_uuid=True), ForeignKey("treasury.id", ondelete="CASCADE"), nullable=False)
    event = Column(String(50), nullable=False, index=True)  # fee_collected, distribution
    amount = Column(Numeric(20, 8), nullable=False)
    reference_type = Column(String(50))
    reference_id = Column(String(255))

    treasury = relationship("Treasury")
