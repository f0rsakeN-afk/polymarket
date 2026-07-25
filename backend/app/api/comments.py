import logging
from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db, get_db_replica
from app.deps import get_current_user
from app.models.market import Market
from app.models.comment import Comment
from app.models.user import User
from app.schemas.comment import CommentCreate, CommentResponse
from app.api.responses import success_response
from app.api.exceptions import NotFoundError, ForbiddenError, ValidationError
from app.websocket.manager import redis_pubsub

logger = logging.getLogger("polymarket")
router = APIRouter(prefix="/markets", tags=["comments"])

MAX_DEPTH = 3


@router.post("/{slug}/comments", summary="Post a comment", description="Create a comment or reply on a market. Auth required.")
async def create_comment(
    slug: str,
    data: CommentCreate,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    user = await get_current_user(request, db)

    market_result = await db.execute(select(Market).where(Market.slug == slug))
    market = market_result.scalar_one_or_none()
    if not market:
        raise NotFoundError("Market not found")

    parent = None
    depth = 0
    if data.parent_id:
        parent_result = await db.execute(
            select(Comment).where(Comment.id == data.parent_id, Comment.market_id == market.id)
        )
        parent = parent_result.scalar_one_or_none()
        if not parent:
            raise ValidationError("Parent comment not found")
        depth = parent.depth + 1
        if depth > MAX_DEPTH:
            raise ValidationError(f"Max reply depth is {MAX_DEPTH}")

    comment = Comment(
        market_id=market.id,
        user_id=user.id,
        parent_id=data.parent_id,
        content=data.content,
        depth=depth,
    )
    db.add(comment)
    await db.commit()
    await db.refresh(comment)

    logger.info(f"Comment created: user={user.id} market={slug}")

    # Broadcast new comment live to WebSocket subscribers
    try:
        await redis_pubsub.publish_market_event(str(market.id), "comment:new", {
            "comment_id": str(comment.id),
            "user_id": str(user.id),
            "username": user.username,
            "content": comment.content,
            "depth": comment.depth,
            "parent_id": str(comment.parent_id) if comment.parent_id else None,
        })
    except Exception:
        pass  # non-fatal

    return success_response({
        "id": str(comment.id),
        "market_id": str(comment.market_id),
        "user_id": str(comment.user_id),
        "username": user.username,
        "parent_id": str(comment.parent_id) if comment.parent_id else None,
        "content": comment.content,
        "depth": comment.depth,
        "is_deleted": comment.is_deleted,
        "reply_count": 0,
        "created_at": comment.created_at.isoformat(),
        "updated_at": comment.updated_at.isoformat(),
    })


@router.get("/{slug}/comments", summary="List comments", description="List comments for a market with nested replies.")
async def list_comments(
    slug: str,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db_replica),
):
    market_result = await db.execute(select(Market).where(Market.slug == slug))
    market = market_result.scalar_one_or_none()
    if not market:
        raise NotFoundError("Market not found")

    # Fetch all top-level comments for this market
    result = await db.execute(
        select(Comment, User.username)
        .join(User, Comment.user_id == User.id)
        .where(Comment.market_id == market.id, Comment.parent_id.is_(None))
        .order_by(Comment.created_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    rows = result.all()

    # Count replies for each top-level comment
    comments_out = []
    for comment, username in rows:
        reply_count_result = await db.execute(
            select(func.count(Comment.id)).where(Comment.parent_id == comment.id)
        )
        reply_count = reply_count_result.scalar() or 0

        comments_out.append({
            "id": str(comment.id),
            "market_id": str(comment.market_id),
            "user_id": str(comment.user_id),
            "username": username,
            "parent_id": None,
            "content": comment.content,
            "depth": comment.depth,
            "is_deleted": comment.is_deleted,
            "reply_count": reply_count,
            "created_at": comment.created_at,
            "updated_at": comment.updated_at,
        })

    return success_response({
        "comments": comments_out,
        "page": page,
        "page_size": page_size,
    })


@router.get("/{slug}/comments/{comment_id}/replies", summary="Get comment replies", description="Get all replies to a specific comment.")
async def get_replies(
    slug: str,
    comment_id: str,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
):
    market_result = await db.execute(select(Market).where(Market.slug == slug))
    market = market_result.scalar_one_or_none()
    if not market:
        raise NotFoundError("Market not found")

    result = await db.execute(
        select(Comment, User.username)
        .join(User, Comment.user_id == User.id)
        .where(Comment.parent_id == comment_id, Comment.market_id == market.id)
        .order_by(Comment.created_at.asc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    rows = result.all()

    replies = []
    for comment, username in rows:
        replies.append({
            "id": str(comment.id),
            "market_id": str(comment.market_id),
            "user_id": str(comment.user_id),
            "username": username,
            "parent_id": str(comment.parent_id) if comment.parent_id else None,
            "content": comment.content,
            "depth": comment.depth,
            "is_deleted": comment.is_deleted,
            "reply_count": 0,
            "created_at": comment.created_at,
            "updated_at": comment.updated_at,
        })

    return success_response({
        "replies": replies,
        "page": page,
        "page_size": page_size,
    })


@router.patch("/{slug}/comments/{comment_id}", summary="Edit comment", description="Edit own comment content. Auth required.")
async def edit_comment(
    slug: str,
    comment_id: str,
    data: CommentCreate,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    user = await get_current_user(request, db)

    market_result = await db.execute(select(Market).where(Market.slug == slug))
    market = market_result.scalar_one_or_none()
    if not market:
        raise NotFoundError("Market not found")

    result = await db.execute(
        select(Comment).where(Comment.id == comment_id, Comment.market_id == market.id)
    )
    comment = result.scalar_one_or_none()
    if not comment:
        raise NotFoundError("Comment not found")
    if str(comment.user_id) != str(user.id):
        raise ForbiddenError("You can only edit your own comments")
    if comment.is_deleted:
        raise ValidationError("Cannot edit a deleted comment")

    comment.content = data.content
    await db.commit()
    await db.refresh(comment)

    return success_response({
        "id": str(comment.id),
        "content": comment.content,
        "updated_at": comment.updated_at.isoformat(),
    })


@router.delete("/{slug}/comments/{comment_id}", summary="Delete comment", description="Soft-delete own comment. Auth required.")
async def delete_comment(
    slug: str,
    comment_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    user = await get_current_user(request, db)

    market_result = await db.execute(select(Market).where(Market.slug == slug))
    market = market_result.scalar_one_or_none()
    if not market:
        raise NotFoundError("Market not found")

    result = await db.execute(
        select(Comment).where(Comment.id == comment_id, Comment.market_id == market.id)
    )
    comment = result.scalar_one_or_none()
    if not comment:
        raise NotFoundError("Comment not found")
    if str(comment.user_id) != str(user.id):
        raise ForbiddenError("You can only delete your own comments")

    comment.is_deleted = True
    await db.commit()

    logger.info(f"Comment deleted: {comment_id} by user={user.id}")
    return success_response({"id": str(comment_id), "status": "deleted"})
