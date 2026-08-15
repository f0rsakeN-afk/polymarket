"""Tests for market activity endpoint."""
import pytest
from uuid import uuid4
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_get_market_activity(client: AsyncClient, test_market):
    """Returns activity feed with stats, holders, trades, comments."""
    resp = await client.get(f"/api/v1/markets/{test_market.slug}/activity")
    assert resp.status_code == 200
    data = resp.json()
    assert data["success"] is True

    activity = data["data"]
    assert "market_stats" in activity
    assert "top_holders_by_outcome" in activity
    assert "recent_trades" in activity
    assert "recent_comments" in activity

    stats = activity["market_stats"]
    assert "total_volume" in stats
    assert "yes_price" in stats
    assert "no_price" in stats


@pytest.mark.asyncio
async def test_get_market_activity_with_limit(client: AsyncClient, test_market):
    """Activity respects limit parameter."""
    resp = await client.get(f"/api/v1/markets/{test_market.slug}/activity?limit=5")
    assert resp.status_code == 200
    data = resp.json()
    assert data["success"] is True


@pytest.mark.asyncio
async def test_get_market_activity_max_limit(client: AsyncClient, test_market):
    """Activity accepts max limit of 100."""
    resp = await client.get(f"/api/v1/markets/{test_market.slug}/activity?limit=100")
    assert resp.status_code == 200
    assert resp.json()["success"] is True


@pytest.mark.asyncio
async def test_get_market_activity_not_found(client: AsyncClient):
    """Returns 404 for non-existent market."""
    resp = await client.get("/api/v1/markets/nonexistent-market/activity")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_get_market_activity_empty_market(client: AsyncClient, db_session, admin_user):
    """Market with no trades, comments, or positions returns empty lists."""
    from datetime import datetime, timezone
    from app.models.market import Market, Outcome

    slug = f"empty-mkt-{uuid4().hex[:8]}"
    market = Market(
        slug=slug,
        question="Will it snow next July?",
        description="Empty market with no activity",
        category="weather",
        status="active",
        created_by=admin_user.id,
        closes_at=datetime(2099, 12, 31, tzinfo=timezone.utc),
        total_liquidity="0.00",
        total_volume="0.00",
    )
    db_session.add(market)
    await db_session.flush()

    yes_outcome = Outcome(market_id=market.id, name="Yes", outcome_index=0)
    no_outcome = Outcome(market_id=market.id, name="No", outcome_index=1)
    db_session.add_all([yes_outcome, no_outcome])
    await db_session.commit()
    await db_session.refresh(market)

    resp = await client.get(f"/api/v1/markets/{slug}/activity")
    assert resp.status_code == 200
    data = resp.json()
    assert data["success"] is True
    activity = data["data"]
    assert activity["recent_trades"] == []
    assert activity["recent_comments"] == []
    assert activity["top_holders_by_outcome"] == {}
    stats = activity["market_stats"]
    assert stats["total_volume"] == 0.0
    assert stats["num_trades"] == 0


@pytest.mark.asyncio
async def test_get_market_activity_resolved(client: AsyncClient, resolved_market):
    """Activity works for resolved markets."""
    resp = await client.get(f"/api/v1/markets/{resolved_market.slug}/activity")
    assert resp.status_code == 200
    data = resp.json()
    assert data["success"] is True
    assert data["data"]["market_stats"]["status"] == "resolved"
