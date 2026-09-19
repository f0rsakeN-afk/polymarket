from sqlalchemy import Boolean, Column, ForeignKey, Index, Integer, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from app.models.base import Base, TimestampMixin, UUIDMixin


class Comment(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "comments"
    __table_args__ = (
        Index("ix_comments_market_id", "market_id"),
        Index("ix_comments_parent_id", "parent_id"),
        Index("ix_comments_market_parent", "market_id", "parent_id"),
    )

    market_id = Column(UUID(as_uuid=True), ForeignKey("markets.id", ondelete="CASCADE"), nullable=False)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    parent_id = Column(UUID(as_uuid=True), ForeignKey("comments.id", ondelete="CASCADE"), nullable=True)
    content = Column(Text, nullable=False)
    depth = Column(Integer, default=0)
    is_deleted = Column(Boolean, default=False)

    market = relationship("Market", back_populates="comments")
    user = relationship("User", back_populates="comments")


Comment.parent = relationship(
    Comment,
    back_populates="replies",
    remote_side=Comment.__table__.c.id,
    foreign_keys=Comment.parent_id,
)
Comment.replies = relationship(
    Comment,
    back_populates="parent",
    foreign_keys=Comment.parent_id,
    cascade="all, delete-orphan",
)
