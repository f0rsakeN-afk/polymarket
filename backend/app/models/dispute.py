from app.models.base import Base, UUIDMixin, TimestampMixin
from sqlalchemy import Column, String, DateTime, Text, ForeignKey
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship


class Dispute(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "disputes"

    market_id = Column(UUID(as_uuid=True), ForeignKey("markets.id", ondelete="CASCADE"), nullable=False)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    evidence = Column(Text, nullable=False)
    evidence_url = Column(String(1000))
    status = Column(String(20), default="open", nullable=False, index=True)

    market = relationship("Market", back_populates="disputes")
    user = relationship("User")
