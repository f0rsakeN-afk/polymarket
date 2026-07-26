import logging
from datetime import datetime
from decimal import Decimal

from fastapi import APIRouter, Depends, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db, get_db_replica
from app.deps import get_current_user
from app.models.market import Market, Outcome
from app.models.order import Order
from app.api.responses import success_response
from app.api.exceptions import NotFoundError
from app.schemas.order import OrderRequest
from app.services.order_service import OrderService

logger = logging.getLogger("polymarket")
router = APIRouter(prefix="/orders", tags=["orders"])


@router.post("/", summary="Place a market order")
async def place_order(data: OrderRequest, request: Request, db: AsyncSession = Depends(get_db)):
    user = await get_current_user(request, db)
    result = await OrderService.execute_order(db, user, data)
    return success_response({
        "order_id": result.order_id,
        "status": result.status,
        "side": result.side,
        "outcome": result.outcome,
        "shares": float(result.shares),
        "price": float(result.price),
        "price_before": float(result.price_before),
        "price_after": float(result.price_after),
        "yes_price_after": float(result.yes_price_after),
        "no_price_after": float(result.no_price_after),
        "slippage": float(result.slippage),
        "fee": float(result.fee),
        "wallet_balance": float(result.wallet_balance),
    })


@router.delete("/{order_id}", summary="Cancel a pending order")
async def cancel_order(order_id: str, request: Request, db: AsyncSession = Depends(get_db)):
    user = await get_current_user(request, db)
    await OrderService.cancel_order(db, user, order_id)
    return success_response({"order_id": order_id, "status": "cancelled"})


@router.get("/{order_id}", summary="Get order details")
async def get_order(order_id: str, request: Request, db: AsyncSession = Depends(get_db_replica)):
    user = await get_current_user(request, db)
    result = await db.execute(
        select(Order, Outcome, Market).where(
            Order.id == order_id,
            Order.user_id == user.id,
            Order.outcome_id == Outcome.id,
            Order.market_id == Market.id,
        )
    )
    row = result.first()
    if not row:
        raise NotFoundError("Order not found")
    order, outcome, market = row
    return success_response({
        "id": str(order.id),
        "market_id": str(order.market_id),
        "market_slug": market.slug,
        "outcome": outcome.name.lower(),
        "side": order.side,
        "order_type": order.order_type,
        "amount": float(order.amount),
        "remaining_amount": float(order.remaining_amount or 0),
        "price": float(order.price),
        "status": order.status,
        "shares_bought": float(order.shares_bought) if order.shares_bought else None,
        "shares_sold": float(order.shares_sold) if order.shares_sold else None,
        "fee": float(order.fees_paid) if order.fees_paid else None,
        "created_at": order.created_at.isoformat() if order.created_at else None,
        "executed_at": order.executed_at.isoformat() if order.executed_at else None,
    })


@router.get("/", summary="List orders")
async def list_orders(
    request: Request,
    page: int = 1,
    page_size: int = 20,
    status: str | None = None,
    side: str | None = None,
    order_type: str | None = None,
    market_id: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    db: AsyncSession = Depends(get_db_replica),
):
    user = await get_current_user(request, db)
    filters = [Order.user_id == user.id]
    if status:
        filters.append(Order.status == status)
    if side:
        filters.append(Order.side == side)
    if order_type:
        filters.append(Order.order_type == order_type)
    if market_id:
        filters.append(Order.market_id == market_id)
    if date_from:
        filters.append(Order.created_at >= datetime.fromisoformat(date_from))
    if date_to:
        filters.append(Order.created_at <= datetime.fromisoformat(date_to))

    count_q = select(func.count()).select_from(Order).where(*filters)
    total_result = await db.execute(count_q)
    total = total_result.scalar() or 0

    result = await db.execute(
        select(Order, Outcome, Market)
        .where(
            *filters,
            Order.outcome_id == Outcome.id,
            Order.market_id == Market.id,
        )
        .order_by(Order.created_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    rows = result.all()
    orders = [
        {
            "id": str(order.id),
            "market_id": str(order.market_id),
            "market_slug": market.slug,
            "market_question": market.question,
            "outcome": outcome.name.lower(),
            "side": order.side,
            "order_type": order.order_type,
            "amount": float(order.amount),
            "remaining_amount": float(order.remaining_amount or 0),
            "price": float(order.price),
            "status": order.status,
            "shares_bought": float(order.shares_bought) if order.shares_bought else None,
            "shares_sold": float(order.shares_sold) if order.shares_sold else None,
            "fees_paid": float(order.fees_paid) if order.fees_paid else None,
            "created_at": order.created_at.isoformat() if order.created_at else None,
            "executed_at": order.executed_at.isoformat() if order.executed_at else None,
        }
        for order, outcome, market in rows
    ]
    return success_response({
        "orders": orders,
        "total": total,
        "page": page,
        "page_size": page_size,
        "has_more": (page * page_size) < total,
    })
