from datetime import datetime

from pydantic import BaseModel, Field


class CommentCreate(BaseModel):
    content: str = Field(..., min_length=1, max_length=2000)
    parent_id: str | None = None


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

    model_config = {"from_attributes": True}
