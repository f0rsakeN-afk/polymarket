from app.models.base import Base, UUIDMixin, TimestampMixin
from sqlalchemy import Column, Text, ForeignKey, Integer
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship


class MarketFAQ(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "market_faqs"

    market_id = Column(UUID(as_uuid=True), ForeignKey("markets.id", ondelete="CASCADE"), nullable=False)
    question = Column(Text, nullable=False)
    answer = Column(Text, nullable=False)
    display_order = Column(Integer, default=0)

    market = relationship("Market", back_populates="faqs")
