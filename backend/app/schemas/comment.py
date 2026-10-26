from datetime import datetime

from pydantic import BaseModel, Field


class CommentVote(BaseModel):
    comment_id: str
    user_id: str
    vote_type: int  # +1 = upvote, -1 = downvote
    is_upvote: bool
    is_downvote: bool
    created_at: datetime


class CommentCreate(BaseModel):
    content: str = Field(..., min_length=1, max_length=2000)
    parent_id: str | None = Field(None, max_length=64)


class CommentResponse(BaseModel):
    id: str
    market_id: str
    user_id: str
    username: str
    parent_id: str | None = None
    content: str
    depth: int
    is_deleted: bool
    reply_count: int
    created_at: datetime
    updated_at: datetime

    # Vote state for the authenticated user
    user_vote_type: int = 0  # +1 = upvote, -1 = downvote, 0 = no vote
    user_has_voted: bool = False

    model_config = {"from_attributes": True}