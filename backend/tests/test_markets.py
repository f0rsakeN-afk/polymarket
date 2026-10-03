"""Tests for market endpoints."""
import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from unittest.mock import patch

import pytest
from conftest import token_for
from httpx import AsyncClient

from app.models.liquidity import LiquidityPool
from app.models.market import Market, Outcome

# ── List markets ────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_list_markets(client: AsyncClient, test_market):
    resp = await client.get("/api/v1/markets/")
    assert resp.status_code == 200
    data = resp.json()
    assert data["success"] is True
    assert "data" in data
    assert isinstance(data["data"], list)


@pytest.mark.asyncio
async def test_list_markets_filtered_by_category(client: AsyncClient, test_market):
    resp = await client.get("/api/v1/markets/?category=weather")
    assert resp.status_code == 200
    assert resp.json()["success"] is True

    resp2 = await client.get("/api/v1/markets/?category=nonexistent")
    assert resp2.json()["success"] is True
    assert len(resp2.json()["data"]) == 0


@pytest.mark.asyncio
async def test_list_markets_sorted(client: AsyncClient, test_market):
    for sort in ["volume", "newest", "closing_soon", "liquidity"]:
        resp = await client.get(f"/api/v1/markets/?sort={sort}")
        assert resp.status_code == 200
        assert resp.json()["success"] is True


@pytest.mark.asyncio
async def test_list_markets_pagination(client: AsyncClient, test_market):
    resp = await client.get("/api/v1/markets/?page=1&page_size=5")
    assert resp.status_code == 200
    data = resp.json()
    assert data["success"] is True
    assert data["page"] == 1
    assert data["page_size"] == 5
    assert isinstance(data["data"], list)


# ── Get market ─────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_get_market(client: AsyncClient, test_market):
    resp = await client.get(f"/api/v1/markets/{test_market.slug}")
    assert resp.status_code == 200
    data = resp.json()
    assert data["success"] is True
    assert data["data"]["slug"] == test_market.slug
    assert data["data"]["question"] == test_market.question


@pytest.mark.asyncio
async def test_get_market_not_found(client: AsyncClient):
    resp = await client.get("/api/v1/markets/nonexistent-market")
    assert resp.status_code == 404
    assert resp.json()["success"] is False


@pytest.mark.asyncio
async def test_get_market_orderbook(client: AsyncClient, test_market):
    resp = await client.get(f"/api/v1/markets/{test_market.slug}/orderbook")
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert "outcomes" in data
    assert "yes" in data["outcomes"] or "no" in data["outcomes"]


# ── Categories ─────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_list_categories(client: AsyncClient, test_market):
    resp = await client.get("/api/v1/markets/categories")
    assert resp.status_code == 200
    data = resp.json()
    assert data["success"] is True
    assert "categories" in data["data"]
    assert "weather" in data["data"]["categories"]


# ── Create market ──────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_create_market_admin(client: AsyncClient, admin_user):
    client.cookies.set("access_token", token_for(admin_user.id))
    resp = await client.post("/api/v1/markets/", json={
        "slug": "new-test-market",
        "question": "Will it snow next week?",
        "description": "A new test market",
        "category": "weather",
        "closes_at": (datetime.now(UTC) + timedelta(days=7)).isoformat(),
    })
    assert resp.status_code == 200
    assert resp.json()["success"] is True
    assert resp.json()["data"]["slug"] == "new-test-market"
    # Admins publish immediately — no review queue.
    assert resp.json()["data"]["status"] == "active"


# ── Market review queue: submit → admin approval → public catalogue ─────────────

async def _make_user(db_session, tag: str, *, email_verified: bool = True):
    """A standalone user with a wallet and a live session (see conftest)."""
    from conftest import create_login_session

    from app.deps import hash_password
    from app.models.user import User
    from app.models.wallet import Wallet

    uid = uuid.uuid4().hex[:8]
    user = User(
        email=f"{tag}_{uid}@example.com",
        username=f"{tag}_{uid}",
        password_hash=hash_password("Sub!Pass1"),
        is_email_verified=email_verified,
        is_active=True,
    )
    db_session.add(user)
    await db_session.flush()
    db_session.add(Wallet(user_id=user.id, balance="1000.00", locked_balance="0", currency="USDC"))
    await create_login_session(db_session, user)
    await db_session.commit()
    await db_session.refresh(user)
    return user


def _submission(slug: str, **overrides) -> dict:
    body = {
        "slug": slug,
        "question": f"Will {slug.replace('-', ' ')} happen?",
        "category": "weather",
        "closes_at": (datetime.now(UTC) + timedelta(days=7)).isoformat(),
    }
    body.update(overrides)
    return body


async def _submit(client: AsyncClient, user, slug: str, **overrides) -> dict:
    client.cookies.set("access_token", token_for(user.id))
    resp = await client.post("/api/v1/markets/", json=_submission(slug, **overrides))
    assert resp.status_code == 200, resp.text
    return resp.json()["data"]


@pytest.mark.asyncio
async def test_create_market_verified_user_pending_review(client: AsyncClient, test_user):
    """A verified (non-admin) user may submit — it enters the review queue."""
    data = await _submit(client, test_user, "user-submitted-market")
    assert data["slug"] == "user-submitted-market"
    assert data["status"] == "pending_review"


@pytest.mark.asyncio
async def test_create_market_unverified_user_forbidden(client: AsyncClient, db_session):
    """Unverified accounts cannot submit markets at all."""
    user = await _make_user(db_session, "unverified", email_verified=False)
    client.cookies.set("access_token", token_for(user.id))
    resp = await client.post("/api/v1/markets/", json=_submission("unverified-market"))
    assert resp.status_code == 403
    assert resp.json()["success"] is False


@pytest.mark.asyncio
async def test_create_market_anonymous_forbidden(client: AsyncClient):
    resp = await client.post("/api/v1/markets/", json=_submission("anon-market"))
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_pending_market_hidden_from_public_catalogue(client: AsyncClient, test_user):
    await _submit(client, test_user, "hidden-market")

    # Anonymous list: not present, no matter the sort.
    for sort in ("newest", "volume", "closing_soon"):
        client.cookies.clear()
        resp = await client.get(f"/api/v1/markets/?sort={sort}&page_size=100")
        assert resp.status_code == 200
        assert "hidden-market" not in {m["slug"] for m in resp.json()["data"]}

    # The public status filter cannot be used to reach unpublished markets.
    resp = await client.get("/api/v1/markets/?status=pending_review")
    assert resp.status_code == 422
    assert resp.json()["error_code"] == "STATUS_NOT_PUBLIC"


@pytest.mark.asyncio
async def test_pending_market_detail_access_control(
    client: AsyncClient, test_user, admin_user, db_session
):
    """Readable by the submitter and admins; 404 (not 403) for everyone else."""
    await _submit(client, test_user, "pending-detail-market")

    # Submitter
    client.cookies.set("access_token", token_for(test_user.id))
    resp = await client.get("/api/v1/markets/pending-detail-market")
    assert resp.status_code == 200

    # Admin
    client.cookies.set("access_token", token_for(admin_user.id))
    resp = await client.get("/api/v1/markets/pending-detail-market")
    assert resp.status_code == 200

    # Another user — existence must not leak
    other = await _make_user(db_session, "bystander")
    client.cookies.set("access_token", token_for(other.id))
    resp = await client.get("/api/v1/markets/pending-detail-market")
    assert resp.status_code == 404

    # Anonymous
    client.cookies.clear()
    resp = await client.get("/api/v1/markets/pending-detail-market")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_pending_market_not_tradable(client: AsyncClient, test_user):
    """Approval is what makes a market tradable — before it, orders are refused."""
    market = await _submit(client, test_user, "untradable-market")
    resp = await client.post("/api/v1/orders/", json={
        "market_id": market["id"],
        "outcome": "yes",
        "side": "buy",
        "order_type": "market",
        "amount": 10.0,
    })
    assert resp.status_code == 400
    assert resp.json()["success"] is False


# ── Moderation endpoints ─────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_admin_approve_market_publishes_it(client: AsyncClient, admin_user, test_user):
    market = await _submit(client, test_user, "approvable-market")

    client.cookies.set("access_token", token_for(admin_user.id))
    resp = await client.post(f"/api/v1/admin/markets/{market['id']}/approve")
    assert resp.status_code == 200, resp.text
    assert resp.json()["data"]["status"] == "active"

    # Now it is public and tradable: anonymous list + detail both work.
    client.cookies.clear()
    resp = await client.get("/api/v1/markets/?sort=newest&page_size=100")
    assert "approvable-market" in {m["slug"] for m in resp.json()["data"]}
    resp = await client.get("/api/v1/markets/approvable-market")
    assert resp.status_code == 200
    assert resp.json()["data"]["status"] == "active"


@pytest.mark.asyncio
async def test_approve_requires_admin(client: AsyncClient, test_user):
    market = await _submit(client, test_user, "self-approve-market")

    client.cookies.set("access_token", token_for(test_user.id))
    resp = await client.post(f"/api/v1/admin/markets/{market['id']}/approve")
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_approve_requires_authentication(client: AsyncClient, test_user):
    market = await _submit(client, test_user, "anon-approve-market")
    client.cookies.clear()
    resp = await client.post(f"/api/v1/admin/markets/{market['id']}/approve")
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_approve_only_pending_market(client: AsyncClient, admin_user, test_user):
    """A market that is already active cannot be 'approved' again."""
    active = await _submit(client, admin_user, "already-active-market")
    client.cookies.set("access_token", token_for(admin_user.id))
    resp = await client.post(f"/api/v1/admin/markets/{active['id']}/approve")
    assert resp.status_code == 422
    assert resp.json()["error_code"] == "MARKET_NOT_PENDING"


@pytest.mark.asyncio
async def test_approve_invalid_and_unknown_market_id(client: AsyncClient, admin_user):
    client.cookies.set("access_token", token_for(admin_user.id))

    resp = await client.post("/api/v1/admin/markets/not-a-uuid/approve")
    assert resp.status_code == 422
    assert resp.json()["error_code"] == "INVALID_ID"

    resp = await client.post(f"/api/v1/admin/markets/{uuid.uuid4()}/approve")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_approve_expired_submission_rejected(client: AsyncClient, admin_user, test_user):
    """An approval arriving after closes_at would publish a dead market."""
    import asyncio

    market = await _submit(
        client, test_user, "expiring-market",
        closes_at=(datetime.now(UTC) + timedelta(seconds=1)).isoformat(),
    )
    await asyncio.sleep(1.2)

    client.cookies.set("access_token", token_for(admin_user.id))
    resp = await client.post(f"/api/v1/admin/markets/{market['id']}/approve")
    assert resp.status_code == 422
    assert resp.json()["error_code"] == "MARKET_ALREADY_CLOSED"


@pytest.mark.asyncio
async def test_admin_reject_market(client: AsyncClient, admin_user, test_user):
    market = await _submit(client, test_user, "rejectable-market")

    client.cookies.set("access_token", token_for(admin_user.id))
    resp = await client.post(f"/api/v1/admin/markets/{market['id']}/reject")
    assert resp.status_code == 200
    assert resp.json()["data"]["status"] == "rejected"

    # Stays out of the catalogue...
    client.cookies.clear()
    resp = await client.get("/api/v1/markets/?sort=newest&page_size=100")
    assert "rejectable-market" not in {m["slug"] for m in resp.json()["data"]}
    # ...and off the trading path, but the submitter can still see their own.
    resp = await client.get("/api/v1/markets/rejectable-market")
    assert resp.status_code == 404
    client.cookies.set("access_token", token_for(test_user.id))
    resp = await client.get("/api/v1/markets/rejectable-market")
    assert resp.status_code == 200

    # Re-rejecting a decided market is a no-op error, not a second decision.
    client.cookies.set("access_token", token_for(admin_user.id))
    resp = await client.post(f"/api/v1/admin/markets/{market['id']}/reject")
    assert resp.status_code == 422
    assert resp.json()["error_code"] == "MARKET_NOT_PENDING"


@pytest.mark.asyncio
async def test_admin_list_markets_access_control(client: AsyncClient, admin_user, test_user):
    await _submit(client, test_user, "queued-market")

    # Non-admin
    client.cookies.set("access_token", token_for(test_user.id))
    resp = await client.get("/api/v1/admin/markets?status=pending_review")
    assert resp.status_code == 403

    # Anonymous
    client.cookies.clear()
    resp = await client.get("/api/v1/admin/markets?status=pending_review")
    assert resp.status_code == 401

    # Admin sees the queue, with the submitter's email for review context
    client.cookies.set("access_token", token_for(admin_user.id))
    resp = await client.get("/api/v1/admin/markets?status=pending_review")
    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] >= 1
    queued = {m["slug"]: m for m in body["data"]}
    assert "queued-market" in queued
    assert queued["queued-market"]["created_by_email"] == test_user.email
    assert queued["queued-market"]["status"] == "pending_review"


@pytest.mark.asyncio
async def test_create_market_past_close_date(client: AsyncClient, admin_user):
    client.cookies.set("access_token", token_for(admin_user.id))
    resp = await client.post("/api/v1/markets/", json={
        "slug": "past-market",
        "question": "Already closed?",
        "category": "test",
        "closes_at": (datetime.now(UTC) - timedelta(days=1)).isoformat(),
    })
    assert resp.status_code == 422
    assert resp.json()["success"] is False


@pytest.mark.asyncio
async def test_create_market_duplicate_slug(client: AsyncClient, admin_user, test_market):
    client.cookies.set("access_token", token_for(admin_user.id))
    resp = await client.post("/api/v1/markets/", json={
        "slug": test_market.slug,
        "question": "Duplicate slug?",
        "category": "test",
        "closes_at": (datetime.now(UTC) + timedelta(days=7)).isoformat(),
    })
    assert resp.status_code == 422
    assert resp.json()["success"] is False


# ── Resolve market ──────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_resolve_market_admin(client: AsyncClient, admin_user, test_market, db_session):
    """Admin can resolve a market and winning outcome is set."""
    outcome_yes = next(o for o in test_market.outcomes if o.name == "Yes")

    client.cookies.set("access_token", token_for(admin_user.id))
    with patch("app.api.markets.resolve_market.delay"):
        resp = await client.post(f"/api/v1/markets/{test_market.slug}/resolve", json={
            "winning_outcome_id": str(outcome_yes.id),
        })

    assert resp.status_code == 200
    data = resp.json()
    assert data["success"] is True
    assert data["data"]["winning_outcome_name"] == "Yes"


@pytest.mark.asyncio
async def test_resolve_market_non_admin_forbidden(client: AsyncClient, test_user, test_market):
    outcome_yes = next(o for o in test_market.outcomes if o.name == "Yes")
    client.cookies.set("access_token", token_for(test_user.id))
    resp = await client.post(f"/api/v1/markets/{test_market.slug}/resolve", json={
        "winning_outcome_id": str(outcome_yes.id),
    })
    assert resp.status_code == 403
    assert resp.json()["success"] is False


@pytest.mark.asyncio
async def test_resolve_market_already_resolved(client: AsyncClient, admin_user, test_market, db_session):
    """Cannot resolve an already-resolved market."""
    outcome_yes = next(o for o in test_market.outcomes if o.name == "Yes")
    client.cookies.set("access_token", token_for(admin_user.id))

    # Resolve once
    with patch("app.api.markets.resolve_market.delay"):
        await client.post(f"/api/v1/markets/{test_market.slug}/resolve", json={
            "winning_outcome_id": str(outcome_yes.id),
        })

    # Try to resolve again with NO outcome
    outcome_no = next(o for o in test_market.outcomes if o.name == "No")
    resp = await client.post(f"/api/v1/markets/{test_market.slug}/resolve", json={
        "winning_outcome_id": str(outcome_no.id),
    })
    assert resp.status_code == 422
    assert resp.json()["success"] is False


# ── Claim winnings ──────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_claim_winnings_unresolved_market(client: AsyncClient, test_user, test_market):
    """Cannot claim from an unresolved market."""
    client.cookies.set("access_token", token_for(test_user.id))
    resp = await client.post(f"/api/v1/markets/{test_market.slug}/claim")
    assert resp.status_code == 422
    assert resp.json()["success"] is False


# ── FAQs ────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_get_faqs(client: AsyncClient, test_market):
    resp = await client.get(f"/api/v1/markets/{test_market.slug}/faqs")
    assert resp.status_code == 200
    assert resp.json()["success"] is True


# ── Price history ──────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_get_price_history(client: AsyncClient, test_market):
    resp = await client.get(f"/api/v1/markets/{test_market.slug}/price-history")
    assert resp.status_code == 200
    assert resp.json()["success"] is True


@pytest.mark.asyncio
async def test_get_price_history_empty(client: AsyncClient, test_market):
    """Market with no price history returns empty samples list."""
    resp = await client.get(f"/api/v1/markets/{test_market.slug}/price-history")
    assert resp.status_code == 200
    data = resp.json()
    assert data["success"] is True
    assert data["data"] == []


# ── Edge cases: list_markets ─────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_list_markets_empty_category(client: AsyncClient, test_market):
    """Empty string category should return all markets (no filter applied)."""
    resp = await client.get("/api/v1/markets/?category=")
    assert resp.status_code == 200
    assert resp.json()["success"] is True
    assert isinstance(resp.json()["data"], list)


@pytest.mark.asyncio
async def test_list_markets_invalid_sort_key(client: AsyncClient, test_market):
    """Invalid sort key is rejected by Query pattern validation (422)."""
    resp = await client.get("/api/v1/markets/?sort=invalid_sort_key")
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_list_markets_page_zero(client: AsyncClient, test_market):
    """page=0 violates ge=1 constraint (422)."""
    resp = await client.get("/api/v1/markets/?page=0")
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_list_markets_page_size_zero(client: AsyncClient, test_market):
    """page_size=0 violates ge=1 constraint (422)."""
    resp = await client.get("/api/v1/markets/?page_size=0")
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_list_markets_page_size_too_large(client: AsyncClient, test_market):
    """page_size=999 exceeds le=100 constraint (422)."""
    resp = await client.get("/api/v1/markets/?page_size=999")
    assert resp.status_code == 422


# ── Edge cases: get_market ──────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_get_market_resolved(resolved_market: Market, client: AsyncClient):
    """Resolved market still returns 200 with resolution data."""
    resp = await client.get(f"/api/v1/markets/{resolved_market.slug}")
    assert resp.status_code == 200
    data = resp.json()
    assert data["success"] is True
    assert data["data"]["status"] == "resolved"
    assert data["data"]["winning_outcome_id"] is not None


@pytest.mark.asyncio
async def test_get_market_zero_volume(client: AsyncClient, admin_user, db_session):
    """Market with zero volume/liquidity still returns 200."""
    from datetime import datetime

    from app.models.market import Market

    m = Market(
        slug=f"zero-vol-{uuid.uuid4().hex[:8]}",
        question="Zero volume market?",
        description="No trades yet",
        category="test",
        status="active",
        created_by=admin_user.id,
        closes_at=datetime(2099, 12, 31, tzinfo=UTC),
        total_liquidity="0",
        total_volume="0",
    )
    db_session.add(m)
    await db_session.flush()
    Outcome(market_id=m.id, name="Yes", outcome_index=0)
    Outcome(market_id=m.id, name="No", outcome_index=1)
    LiquidityPool(market_id=m.id, yes_shares="0", no_shares="0", collateral="0", lp_token_supply="0")
    await db_session.commit()

    resp = await client.get(f"/api/v1/markets/{m.slug}")
    assert resp.status_code == 200
    assert Decimal(resp.json()["data"]["total_volume"]) == 0


# ── Edge cases: get_orderbook ───────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_get_orderbook_empty(client: AsyncClient, admin_user, db_session):
    """Market with no pending orders returns empty bids and asks."""
    from datetime import datetime

    from app.models.market import Market

    m = Market(
        slug=f"empty-book-{uuid.uuid4().hex[:8]}",
        question="No orders here?",
        description="Empty orderbook",
        category="test",
        status="active",
        created_by=admin_user.id,
        closes_at=datetime(2099, 12, 31, tzinfo=UTC),
    )
    db_session.add(m)
    await db_session.flush()
    Outcome(market_id=m.id, name="Yes", outcome_index=0)
    Outcome(market_id=m.id, name="No", outcome_index=1)
    await db_session.commit()

    resp = await client.get(f"/api/v1/markets/{m.slug}/orderbook")
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert "outcomes" in data
    for outcome in data["outcomes"].values():
        assert outcome["bids"] == []
        assert outcome["asks"] == []


# ── Edge cases: create_market ──────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_create_market_missing_required_fields(client: AsyncClient, admin_user):
    """POST with missing required fields returns 422."""
    client.cookies.set("access_token", token_for(admin_user.id))
    resp = await client.post("/api/v1/markets/", json={
        "slug": "incomplete-market",
        # missing question, category, closes_at
    })
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_create_market_empty_question(client: AsyncClient, admin_user):
    """POST with empty question/description is rejected."""
    client.cookies.set("access_token", token_for(admin_user.id))
    resp = await client.post("/api/v1/markets/", json={
        "slug": f"empty-q-{uuid.uuid4().hex[:8]}",
        "question": "   ",
        "description": "",
        "category": "test",
        "closes_at": (datetime.now(UTC) + timedelta(days=7)).isoformat(),
    })
    assert resp.status_code == 422


# ── Edge cases: resolve_market ─────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_resolve_market_missing_winning_outcome(client: AsyncClient, admin_user, test_market):
    """Resolve without winning_outcome_id fails validation."""
    client.cookies.set("access_token", token_for(admin_user.id))
    resp = await client.post(
        f"/api/v1/markets/{test_market.slug}/resolve",
        json={},
    )
    assert resp.status_code == 422


# ── Edge cases: claim_winnings ────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_claim_no_winning_position(client: AsyncClient, test_user, resolved_market):
    """User with no winning position gets a clear error."""
    client.cookies.set("access_token", token_for(test_user.id))
    resp = await client.post(f"/api/v1/markets/{resolved_market.slug}/claim")
    assert resp.status_code == 422
    assert resp.json()["success"] is False


@pytest.mark.asyncio
async def test_claim_idempotent(client: AsyncClient, admin_user, db_session, test_user):
    """Claiming twice on same resolved market returns 422 second time."""
    from datetime import datetime

    from app.models.market import Market
    from app.models.position import Position

    # Create our own resolved market so we don't mutate test_market
    slug = f"idem-{uuid.uuid4().hex[:8]}"
    m = Market(
        slug=slug,
        question="Will claim twice work?",
        description="Idempotency test",
        category="test",
        status="active",
        created_by=admin_user.id,
        closes_at=datetime(2099, 12, 31, tzinfo=UTC),
    )
    db_session.add(m)
    await db_session.flush()
    yes_outcome = Outcome(market_id=m.id, name="Yes", outcome_index=0)
    no_outcome = Outcome(market_id=m.id, name="No", outcome_index=1)
    db_session.add(yes_outcome)
    db_session.add(no_outcome)
    await db_session.flush()
    # Refresh to ensure UUID IDs are populated from DB
    await db_session.refresh(yes_outcome)
    await db_session.refresh(no_outcome)

    m.status = "resolved"
    m.winning_outcome_id = yes_outcome.id
    await db_session.flush()

    pos = Position(
        user_id=test_user.id,
        market_id=m.id,
        outcome_id=yes_outcome.id,
        shares_held="10.0",
        average_price="0.5",
    )
    db_session.add(pos)
    await db_session.commit()

    client.cookies.set("access_token", token_for(test_user.id))

    r1 = await client.post(f"/api/v1/markets/{slug}/claim")
    assert r1.status_code == 200

    r2 = await client.post(f"/api/v1/markets/{slug}/claim")
    assert r2.status_code == 422


# ── Related markets ─────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_get_related(client: AsyncClient, test_market):
    resp = await client.get(f"/api/v1/markets/{test_market.slug}/related")
    assert resp.status_code == 200
    assert resp.json()["success"] is True


# ── Helpers ────────────────────────────────────────────────────────────────────

