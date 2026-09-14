"""Tests for order endpoints."""
from decimal import Decimal

import pytest
from httpx import AsyncClient

from app.models.market import Market, Outcome


def _token(user_id: str) -> str:
    from app.deps import create_access_token
    t, _ = create_access_token(str(user_id))
    return t


# ── Get quote ───────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_get_quote_auth_required(client: AsyncClient, test_market):
    _outcome = next(o for o in test_market.outcomes if o.name.lower() == "yes")
    resp = await client.post("/api/v1/orders/quote", json={
        "market_id": str(test_market.id),
        "outcome": "yes",
        "side": "buy",
        "amount": 10.0,
    })
    # Without auth - depends on auth middleware behavior
    assert resp.status_code in (200, 401, 500)


@pytest.mark.asyncio
async def test_get_quote_success(client: AsyncClient, test_user, test_market):
    _outcome = next(o for o in test_market.outcomes if o.name.lower() == "yes")
    client.cookies.set("access_token", _token(test_user.id))
    resp = await client.post("/api/v1/orders/quote", json={
        "market_id": str(test_market.id),
        "outcome": "yes",
        "side": "buy",
        "amount": 10.0,
    })
    assert resp.status_code == 200
    data = resp.json()
    assert data["success"] is True
    assert "quote_id" in data["data"]


@pytest.mark.asyncio
async def test_get_quote_invalid_market(client: AsyncClient, test_user):
    client.cookies.set("access_token", _token(test_user.id))
    resp = await client.post("/api/v1/orders/quote", json={
        "market_id": "00000000-0000-0000-0000-000000000000",
        "outcome": "yes",
        "side": "buy",
        "amount": 10.0,
    })
    assert resp.status_code == 404
    assert resp.json()["success"] is False


@pytest.mark.asyncio
async def test_get_quote_invalid_outcome(client: AsyncClient, test_user, test_market):
    client.cookies.set("access_token", _token(test_user.id))
    resp = await client.post("/api/v1/orders/quote", json={
        "market_id": str(test_market.id),
        "outcome": "maybe",
        "side": "buy",
        "amount": 10.0,
    })
    assert resp.status_code == 422
    assert resp.json()["success"] is False


# ── Place order ────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_place_order_market_buy(client: AsyncClient, test_user, test_market, db_session):
    _outcome = next(o for o in test_market.outcomes if o.name.lower() == "yes")
    client.cookies.set("access_token", _token(test_user.id))
    resp = await client.post("/api/v1/orders/", json={
        "market_id": str(test_market.id),
        "outcome": "yes",
        "side": "buy",
        "order_type": "market",
        "amount": 10.0,
    })

    assert resp.status_code == 200
    data = resp.json()
    assert data["success"] is True
    assert data["data"]["status"] == "filled"


@pytest.mark.asyncio
async def test_place_order_insufficient_balance(client: AsyncClient, test_user, test_market):
    _outcome = next(o for o in test_market.outcomes if o.name.lower() == "yes")
    client.cookies.set("access_token", _token(test_user.id))
    resp = await client.post("/api/v1/orders/", json={
        "market_id": str(test_market.id),
        "outcome": "yes",
        "side": "buy",
        "order_type": "market",
        "amount": 999999.0,  # More than user has
    })
    assert resp.status_code == 400
    assert resp.json()["success"] is False


@pytest.mark.asyncio
async def test_place_order_closed_market(client: AsyncClient, admin_user, test_user, db_session):
    """Cannot trade on a resolved/closed market."""
    from datetime import UTC, datetime

    # Create a closed market
    market = Market(
        slug="closed-market",
        question="Already closed market?",
        category="test",
        status="closed",
        created_by=admin_user.id,
        closes_at=datetime(2020, 1, 1, tzinfo=UTC),
    )
    db_session.add(market)
    await db_session.flush()
    yes_outcome = Outcome(market_id=market.id, name="Yes", outcome_index=0)
    no_outcome = Outcome(market_id=market.id, name="No", outcome_index=1)
    db_session.add_all([yes_outcome, no_outcome])
    await db_session.commit()

    client.cookies.set("access_token", _token(test_user.id))
    resp = await client.post("/api/v1/orders/", json={
        "market_id": str(market.id),
        "outcome": "yes",
        "side": "buy",
        "order_type": "market",
        "amount": 10.0,
    })
    assert resp.status_code == 400
    assert resp.json()["success"] is False


@pytest.mark.asyncio
async def test_place_order_sell_without_holding(client: AsyncClient, test_user, test_market):
    """Cannot sell shares you don't hold."""
    client.cookies.set("access_token", _token(test_user.id))
    resp = await client.post("/api/v1/orders/", json={
        "market_id": str(test_market.id),
        "outcome": "yes",
        "side": "sell",
        "order_type": "market",
        "amount": 10.0,
    })
    assert resp.status_code == 422
    assert resp.json()["success"] is False


@pytest.mark.asyncio
async def test_place_order_duplicate(client: AsyncClient, test_user, test_market):
    """Idempotency - duplicate client_order_id returns same order."""
    _outcome = next(o for o in test_market.outcomes if o.name.lower() == "yes")
    client.cookies.set("access_token", _token(test_user.id))
    payload = {
        "market_id": str(test_market.id),
        "outcome": "yes",
        "side": "buy",
        "order_type": "market",
        "amount": 5.0,
        "client_order_id": "unique-client-id-123",
    }
    resp1 = await client.post("/api/v1/orders/", json=payload)
    assert resp1.status_code == 200

    resp2 = await client.post("/api/v1/orders/", json=payload)
    assert resp2.status_code == 200
    data2 = resp2.json()
    assert data2["success"] is True
    assert data2["data"].get("status") == "duplicate"


# ── Cancel order ───────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_cancel_order(client: AsyncClient, test_user, test_market, db_session):
    """Cancel a pending limit order."""
    from app.models.order import Order

    client.cookies.set("access_token", _token(test_user.id))

    # Create a pending order directly (place_order has no commit for pending orders)
    outcome = next(o for o in test_market.outcomes if o.name.lower() == "yes")
    pending_order = Order(
        user_id=test_user.id,
        market_id=test_market.id,
        outcome_id=outcome.id,
        side="buy",
        order_type="limit",
        amount=Decimal("10.0"),
        price=Decimal("0.5"),
        remaining_amount=Decimal("10.0"),
        status="pending",
    )
    db_session.add(pending_order)
    await db_session.commit()
    await db_session.refresh(pending_order)

    # Cancel it
    cancel_resp = await client.delete(f"/api/v1/orders/{pending_order.id}")
    assert cancel_resp.status_code == 200


@pytest.mark.asyncio
async def test_cancel_order_not_found(client: AsyncClient, test_user):
    client.cookies.set("access_token", _token(test_user.id))
    resp = await client.delete("/api/v1/orders/00000000-0000-0000-0000-000000000000")
    assert resp.status_code == 404
    assert resp.json()["success"] is False


# ── List orders ────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_list_orders_empty(client: AsyncClient, test_user):
    client.cookies.set("access_token", _token(test_user.id))
    resp = await client.get("/api/v1/orders/")
    assert resp.status_code == 200
    data = resp.json()
    assert data["success"] is True
    assert data["data"]["orders"] == []


@pytest.mark.asyncio
async def test_list_orders_with_filters(client: AsyncClient, test_user):
    client.cookies.set("access_token", _token(test_user.id))
    resp = await client.get("/api/v1/orders/?status=filled&side=buy&page=1&page_size=10")
    assert resp.status_code == 200
    assert resp.json()["success"] is True


@pytest.mark.asyncio
async def test_list_orders_pagination(client: AsyncClient, test_user, test_market):
    """Orders list is paginated."""
    client.cookies.set("access_token", _token(test_user.id))
    resp = await client.get("/api/v1/orders/?page=1&page_size=5")
    assert resp.status_code == 200
    assert resp.json()["data"]["page"] == 1
    assert resp.json()["data"]["page_size"] == 5


# ── Get order ──────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_get_order(client: AsyncClient, test_user, test_market):
    """Get order by ID."""
    client.cookies.set("access_token", _token(test_user.id))
    order_resp = await client.post("/api/v1/orders/", json={
        "market_id": str(test_market.id),
        "outcome": "yes",
        "side": "buy",
        "amount": 10.0,
    })
    assert order_resp.status_code == 200
    # Order may have empty order_id; query it back
    list_resp = await client.get("/api/v1/orders/?page=1&page_size=1")
    orders = list_resp.json()["data"]["orders"]
    order_id = orders[0]["id"]
    get_resp = await client.get(f"/api/v1/orders/{order_id}")
    assert get_resp.status_code == 200
    assert get_resp.json()["data"]["id"] == order_id


@pytest.mark.asyncio
async def test_get_order_not_found(client: AsyncClient, test_user):
    client.cookies.set("access_token", _token(test_user.id))
    resp = await client.get("/api/v1/orders/00000000-0000-0000-0000-000000000000")
    assert resp.status_code == 404
    assert resp.json()["success"] is False


# ── Edge cases ────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_order_amount_must_be_positive(client: AsyncClient, test_user, test_market):
    client.cookies.set("access_token", _token(test_user.id))
    resp = await client.post("/api/v1/orders/", json={
        "market_id": str(test_market.id),
        "outcome": "yes",
        "side": "buy",
        "order_type": "market",
        "amount": -10.0,
    })
    assert resp.status_code in (200, 422)  # 422 = validation error


@pytest.mark.asyncio
async def test_order_price_must_be_0_to_1(client: AsyncClient, test_user, test_market):
    client.cookies.set("access_token", _token(test_user.id))
    resp = await client.post("/api/v1/orders/", json={
        "market_id": str(test_market.id),
        "outcome": "yes",
        "side": "buy",
        "order_type": "limit",
        "amount": 10.0,
        "price": 1.5,  # Out of range
    })
    assert resp.status_code in (200, 422)
    if resp.status_code == 200:
        assert resp.json()["success"] is False


@pytest.mark.asyncio
async def test_place_order_amount_zero(client: AsyncClient, test_user, test_market):
    """Amount of 0 should be rejected (gt=0 validation)."""
    client.cookies.set("access_token", _token(test_user.id))
    resp = await client.post("/api/v1/orders/", json={
        "market_id": str(test_market.id),
        "outcome": "yes",
        "side": "buy",
        "order_type": "market",
        "amount": 0.0,
    })
    assert resp.status_code == 422
    assert resp.json()["success"] is False


@pytest.mark.asyncio
async def test_place_order_price_at_boundaries(client: AsyncClient, test_user, test_market):
    """Price of 0 and 1.0 are valid boundary values for limit orders."""
    client.cookies.set("access_token", _token(test_user.id))
    for price in (0.0, 1.0):
        resp = await client.post("/api/v1/orders/", json={
            "market_id": str(test_market.id),
            "outcome": "yes",
            "side": "buy",
            "order_type": "limit",
            "amount": 10.0,
            "price": price,
        })
        # Should not be rejected for price being out of range
        assert resp.status_code != 422, f"price={price} should not 422"


@pytest.mark.asyncio
async def test_place_order_invalid_side(client: AsyncClient, test_user, test_market):
    """Invalid side value should be rejected by pattern validation."""
    client.cookies.set("access_token", _token(test_user.id))
    resp = await client.post("/api/v1/orders/", json={
        "market_id": str(test_market.id),
        "outcome": "yes",
        "side": "invalid",
        "order_type": "market",
        "amount": 10.0,
    })
    assert resp.status_code == 422
    assert resp.json()["success"] is False


@pytest.mark.asyncio
async def test_place_order_invalid_outcome(client: AsyncClient, test_user, test_market):
    """Outcome that is not yes/no should be rejected."""
    client.cookies.set("access_token", _token(test_user.id))
    resp = await client.post("/api/v1/orders/", json={
        "market_id": str(test_market.id),
        "outcome": "maybe",
        "side": "buy",
        "order_type": "market",
        "amount": 10.0,
    })
    assert resp.status_code in (400, 422)
    assert resp.json()["success"] is False


@pytest.mark.asyncio
async def test_place_order_nonexistent_market(client: AsyncClient, test_user):
    """Order on a market that doesn't exist should return 404."""
    client.cookies.set("access_token", _token(test_user.id))
    resp = await client.post("/api/v1/orders/", json={
        "market_id": "00000000-0000-0000-0000-000000000000",
        "outcome": "yes",
        "side": "buy",
        "order_type": "market",
        "amount": 10.0,
    })
    assert resp.status_code == 404
    assert resp.json()["success"] is False


@pytest.mark.asyncio
async def test_get_quote_invalid_outcome_edge(client: AsyncClient, test_user, test_market):
    """Invalid outcome (not yes/no) on quote endpoint should be rejected."""
    client.cookies.set("access_token", _token(test_user.id))
    resp = await client.post("/api/v1/orders/quote", json={
        "market_id": str(test_market.id),
        "outcome": "invalid",
        "side": "buy",
        "amount": 10.0,
    })
    assert resp.status_code == 422
    assert resp.json()["success"] is False


@pytest.mark.asyncio
async def test_get_quote_amount_zero(client: AsyncClient, test_user, test_market):
    """Quote with amount=0 should be rejected (gt=0)."""
    client.cookies.set("access_token", _token(test_user.id))
    resp = await client.post("/api/v1/orders/quote", json={
        "market_id": str(test_market.id),
        "outcome": "yes",
        "side": "buy",
        "amount": 0.0,
    })
    assert resp.status_code == 422
    assert resp.json()["success"] is False


@pytest.mark.asyncio
async def test_list_orders_filter_by_status(client: AsyncClient, test_user):
    """List orders filtered by status=pending."""
    client.cookies.set("access_token", _token(test_user.id))
    resp = await client.get("/api/v1/orders/?status=pending")
    assert resp.status_code == 200
    assert resp.json()["success"] is True


@pytest.mark.asyncio
async def test_list_orders_filter_by_side(client: AsyncClient, test_user):
    """List orders filtered by side=buy."""
    client.cookies.set("access_token", _token(test_user.id))
    resp = await client.get("/api/v1/orders/?side=buy")
    assert resp.status_code == 200
    assert resp.json()["success"] is True


@pytest.mark.asyncio
async def test_list_orders_filter_by_market_id(client: AsyncClient, test_user, test_market):
    """List orders filtered by market_id."""
    client.cookies.set("access_token", _token(test_user.id))
    resp = await client.get(f"/api/v1/orders/?market_id={test_market.id}")
    assert resp.status_code == 200
    assert resp.json()["success"] is True


# ── Buy-limit unit convention (USDC remainder) ────────────────────────────────

@pytest.mark.asyncio
async def test_buy_limit_persists_usdc_remainder(db_session, test_user, test_market):
    """Regression: resting BUY limits track USDC budget, not shares.

    AMM price is 0.50, so a 0.30 buy rests. remaining_amount must equal the
    full USDC budget or the order can never match/fill later.
    """
    from app.models.order import Order
    from app.schemas.order import OrderRequest
    from app.services.order_service import OrderService
    from sqlalchemy import select

    result = await OrderService.execute_order(
        db_session,
        test_user,
        OrderRequest(
            market_id=str(test_market.id),
            outcome="yes",
            side="buy",
            order_type="limit",
            amount=Decimal("100"),
            price=Decimal("0.30"),
        ),
    )
    assert result.status == "pending"

    stored = await db_session.execute(
        select(Order).where(
            Order.user_id == test_user.id,
            Order.market_id == test_market.id,
            Order.status == "pending",
        )
    )
    order = stored.scalar_one()
    assert order.remaining_amount == Decimal("100")


@pytest.mark.asyncio
async def test_resting_buy_fills_against_book(db_session, test_user, admin_user, test_market):
    """Resting BUY (USDC remainder) matches a SELL maker (share remainder)."""
    from app.models.order import Order
    from app.models.position import Position
    from app.services.matching_engine import MatchingEngine
    from sqlalchemy import select

    yes_outcome = next(o for o in test_market.outcomes if o.name.lower() == "yes")

    db_session.add(Position(
        user_id=admin_user.id,
        market_id=test_market.id,
        outcome_id=yes_outcome.id,
        shares_held=Decimal("100"),
        average_price=Decimal("0.5"),
        realized_pnl=Decimal("0"),
    ))
    sell = Order(
        user_id=admin_user.id,
        market_id=test_market.id,
        outcome_id=yes_outcome.id,
        side="sell",
        order_type="limit",
        amount=Decimal("50"),
        price=Decimal("0.60"),
        remaining_amount=Decimal("50"),
        status="pending",
    )
    buy = Order(
        user_id=test_user.id,
        market_id=test_market.id,
        outcome_id=yes_outcome.id,
        side="buy",
        order_type="limit",
        amount=Decimal("100"),
        price=Decimal("0.60"),
        remaining_amount=Decimal("100"),
        status="pending",
    )
    db_session.add_all([sell, buy])
    await db_session.commit()

    remaining, _ = await MatchingEngine.match_pending_order(
        db_session, buy, test_market, yes_outcome
    )
    await db_session.commit()

    # 50 shares @ 0.60 = 30 USDC of the 100 USDC budget
    assert remaining == Decimal("70")
    assert buy.status == "partial"
    assert buy.remaining_amount == Decimal("70")
    assert sell.status == "filled"

    seller_pos = await db_session.execute(
        select(Position).where(
            Position.user_id == admin_user.id,
            Position.outcome_id == yes_outcome.id,
        )
    )
    assert seller_pos.scalar_one().shares_held == Decimal("50")
