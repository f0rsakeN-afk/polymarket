"""Tests for dispute endpoints."""
import pytest
from unittest.mock import patch

from httpx import AsyncClient


def _token(user_id: str) -> str:
    from app.deps import create_access_token
    t, _ = create_access_token(str(user_id))
    return t


# ── Create dispute ───────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_create_dispute_resolved_market(client: AsyncClient, admin_user, test_user, test_market, db_session):
    """User can file a dispute on a resolved market."""
    outcome = next(o for o in test_market.outcomes if o.name == "Yes")
    client.cookies.set("access_token", _token(admin_user.id))
    with patch("app.api.markets.resolve_market.delay"):
        await client.post(f"/api/v1/markets/{test_market.slug}/resolve", json={
            "winning_outcome_id": str(outcome.id),
        })

    client.cookies.set("access_token", _token(test_user.id))
    resp = await client.post("/api/v1/disputes", json={
        "market_id": str(test_market.id),
        "evidence": "The ruling was incorrect",
        "evidence_url": "https://example.com/proof",
    })
    assert resp.status_code == 200
    data = resp.json()
    assert data["success"] is True
    assert data["data"]["evidence"] == "The ruling was incorrect"


@pytest.mark.asyncio
async def test_create_dispute_active_market_rejected(client: AsyncClient, admin_user, test_user, test_market):
    """Cannot file a dispute on an active (non-resolved) market."""
    client.cookies.set("access_token", _token(test_user.id))
    resp = await client.post("/api/v1/disputes", json={
        "market_id": str(test_market.id),
        "evidence": "Too early to dispute",
    })
    assert resp.status_code == 422
    assert resp.json()["success"] is False


@pytest.mark.asyncio
async def test_create_dispute_nonexistent_market(client: AsyncClient, test_user):
    """Dispute on non-existent market returns 404."""
    client.cookies.set("access_token", _token(test_user.id))
    import uuid
    resp = await client.post("/api/v1/disputes", json={
        "market_id": str(uuid.uuid4()),
        "evidence": "Does not exist",
    })
    assert resp.status_code == 404
    assert resp.json()["success"] is False


@pytest.mark.asyncio
async def test_create_dispute_unauthenticated(client: AsyncClient, test_market):
    """Unauthenticated users cannot file disputes."""
    resp = await client.post("/api/v1/disputes", json={
        "market_id": str(test_market.id),
        "evidence": "Unauthorized access",
    })
    assert resp.status_code == 401


# ── Propose resolution ──────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_propose_resolution_admin(client: AsyncClient, admin_user, test_market):
    """Admin can propose a resolution, opening a dispute window."""
    outcome = next(o for o in test_market.outcomes if o.name == "Yes")
    client.cookies.set("access_token", _token(admin_user.id))
    resp = await client.post("/api/v1/disputes/propose-resolution", json={
        "market_id": str(test_market.id),
        "outcome_id": str(outcome.id),
        "resolution_source": "https://example.com/source",
    })
    assert resp.status_code == 200
    assert resp.json()["success"] is True


@pytest.mark.asyncio
async def test_propose_resolution_non_admin_forbidden(client: AsyncClient, test_user, test_market):
    """Non-admin cannot propose resolutions."""
    outcome = next(o for o in test_market.outcomes if o.name == "Yes")
    client.cookies.set("access_token", _token(test_user.id))
    resp = await client.post("/api/v1/disputes/propose-resolution", json={
        "market_id": str(test_market.id),
        "outcome_id": str(outcome.id),
        "resolution_source": "https://example.com/source",
    })
    assert resp.status_code == 403
    assert resp.json()["success"] is False


# ── Get disputes for market ────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_get_disputes_for_market(client: AsyncClient, admin_user, test_user, test_market, db_session):
    """Disputes filed for a market are retrievable."""
    from app.models.dispute import Dispute

    outcome = next(o for o in test_market.outcomes if o.name == "Yes")
    client.cookies.set("access_token", _token(admin_user.id))
    with patch("app.api.markets.resolve_market.delay"):
        await client.post(f"/api/v1/markets/{test_market.slug}/resolve", json={
            "winning_outcome_id": str(outcome.id),
        })

    client.cookies.set("access_token", _token(test_user.id))
    await client.post("/api/v1/disputes", json={
        "market_id": str(test_market.id),
        "evidence": "My dispute evidence",
    })

    client.cookies.set("access_token", _token(admin_user.id))
    resp = await client.get(f"/api/v1/disputes/market/{test_market.id}")
    assert resp.status_code == 200
    data = resp.json()
    assert data["success"] is True
    assert len(data["data"]) == 1


# ── Adjudicate dispute ──────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_adjudicate_dispute_upheld(client: AsyncClient, admin_user, test_user, test_market, db_session):
    """Admin upholds dispute and market is resolved to proposed outcome."""
    from app.models.dispute import Dispute
    from unittest.mock import patch

    outcome_yes = next(o for o in test_market.outcomes if o.name == "Yes")
    outcome_no = next(o for o in test_market.outcomes if o.name == "No")

    # Propose resolution first
    client.cookies.set("access_token", _token(admin_user.id))
    await client.post("/api/v1/disputes/propose-resolution", json={
        "market_id": str(test_market.id),
        "outcome_id": str(outcome_yes.id),
        "resolution_source": "https://example.com/source",
    })

    # File dispute
    client.cookies.set("access_token", _token(test_user.id))
    d_resp = await client.post("/api/v1/disputes", json={
        "market_id": str(test_market.id),
        "evidence": "Evidence is valid here",
    })
    dispute_id = d_resp.json()["data"]["id"]

    # Adjudicate — uphold (mock Celery delay since no broker is running)
    client.cookies.set("access_token", _token(admin_user.id))
    with patch("app.workers.tasks.resolve_market.delay"):
        resp = await client.post(f"/api/v1/disputes/{dispute_id}/adjudicate", json={
            "ruling": "upheld",
        })
    assert resp.status_code == 200
    data = resp.json()
    assert data["data"]["ruling"] == "upheld"
    assert data["data"]["market_status"] == "resolved"


@pytest.mark.asyncio
async def test_adjudicate_dispute_dismissed(client: AsyncClient, admin_user, test_user, test_market, db_session):
    """Admin dismisses dispute — market status stays dispute_window."""
    from app.models.dispute import Dispute

    outcome = next(o for o in test_market.outcomes if o.name == "Yes")

    client.cookies.set("access_token", _token(admin_user.id))
    await client.post("/api/v1/disputes/propose-resolution", json={
        "market_id": str(test_market.id),
        "outcome_id": str(outcome.id),
        "resolution_source": "https://example.com/source",
    })

    client.cookies.set("access_token", _token(test_user.id))
    d_resp = await client.post("/api/v1/disputes", json={
        "market_id": str(test_market.id),
        "evidence": "Dismiss this",
    })
    dispute_id = d_resp.json()["data"]["id"]

    client.cookies.set("access_token", _token(admin_user.id))
    resp = await client.post(f"/api/v1/disputes/{dispute_id}/adjudicate", json={
        "ruling": "dismissed",
    })
    assert resp.status_code == 200
    assert resp.json()["data"]["ruling"] == "dismissed"
    assert resp.json()["data"]["market_status"] is None


@pytest.mark.asyncio
async def test_adjudicate_dispute_non_admin_forbidden(client: AsyncClient, admin_user, test_user, test_market, db_session):
    """Non-admin cannot adjudicate disputes."""
    from app.models.dispute import Dispute

    outcome = next(o for o in test_market.outcomes if o.name == "Yes")

    client.cookies.set("access_token", _token(admin_user.id))
    await client.post("/api/v1/disputes/propose-resolution", json={
        "market_id": str(test_market.id),
        "outcome_id": str(outcome.id),
        "resolution_source": "https://example.com/source",
    })

    client.cookies.set("access_token", _token(test_user.id))
    d_resp = await client.post("/api/v1/disputes", json={
        "market_id": str(test_market.id),
        "evidence": "Try to adjudicate",
    })
    dispute_id = d_resp.json()["data"]["id"]

    client.cookies.set("access_token", _token(test_user.id))
    resp = await client.post(f"/api/v1/disputes/{dispute_id}/adjudicate", json={
        "ruling": "dismissed",
    })
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_adjudicate_dispute_invalid_ruling(client: AsyncClient, admin_user, test_user, test_market, db_session):
    """Ruling must be 'upheld' or 'dismissed'."""
    from app.models.dispute import Dispute

    outcome = next(o for o in test_market.outcomes if o.name == "Yes")

    client.cookies.set("access_token", _token(admin_user.id))
    await client.post("/api/v1/disputes/propose-resolution", json={
        "market_id": str(test_market.id),
        "outcome_id": str(outcome.id),
        "resolution_source": "https://example.com/source",
    })

    client.cookies.set("access_token", _token(test_user.id))
    d_resp = await client.post("/api/v1/disputes", json={
        "market_id": str(test_market.id),
        "evidence": "Evidence is valid here",
    })
    dispute_id = d_resp.json()["data"]["id"]

    client.cookies.set("access_token", _token(admin_user.id))
    resp = await client.post(f"/api/v1/disputes/{dispute_id}/adjudicate", json={
        "ruling": "invalid_ruling",
    })
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_adjudicate_nonexistent_dispute(client: AsyncClient, admin_user):
    """Adjudicating non-existent dispute returns 404."""
    import uuid
    client.cookies.set("access_token", _token(admin_user.id))
    resp = await client.post(f"/api/v1/disputes/{uuid.uuid4()}/adjudicate", json={
        "ruling": "dismissed",
    })
    assert resp.status_code == 404
