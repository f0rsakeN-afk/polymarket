from sqlalchemy import Boolean, Column, ForeignKey, Index, Integer
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from app.models.base import Base
from app.models.comment import Comment
from app.models.user import User


class CommentVote(Base):
    __tablename__ = "comment_votes"

    __table_args__ = (
        Index("ix_comment_votes_comment", "comment_id"),
        Index("ix_comment_votes_user", "user_id"),
        Index(
            "ix_comment_votes_comment_user",
            "comment_id",
            "user_id",
            unique=True,
        ),
    )

    id = Column(UUID(as_uuid=True), primary_key=True)
    comment_id = Column(
        UUID(as_uuid=True), ForeignKey("comments.id", ondelete="CASCADE"), nullable=False
    )
    user_id = Column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    # +1 = upvote, -1 = downvote, 0 = no vote (for soft removal)
    vote_type = Column(Integer, nullable=False, default=0)
    # Track which direction the user voted
    is_upvote = Column(Boolean, nullable=False, default=False)
    is_downvote = Column(Boolean, nullable=False, default=False)

    comment = relationship("Comment", back_populates="votes")
    user = relationship("User", back_populates="comment_votes")