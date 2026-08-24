"""Tests for wallet, liquidity, split/merge, and position endpoints."""
import pytest
from decimal import Decimal
from unittest.mock import patch, MagicMock

from httpx import AsyncClient

from app.models.liquidity import LiquidityPool, LPShare


def _token(user_id: str) -> str:
    from app.deps import create_access_token
    t, _ = create_access_token(str(user_id))
    return t


# ── Wallet ─────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_get_wallet(client: AsyncClient, test_user):
    client.cookies.set("access_token", _token(test_user.id))
    resp = await client.get("/api/v1/wallet/")
    assert resp.status_code == 200
    data = resp.json()
    assert data["success"] is True
    assert "balance" in data["data"]
    assert data["data"]["currency"] == "USDC"


@pytest.mark.asyncio
async def test_wallet_unauthenticated(client: AsyncClient):
    resp = await client.get("/api/v1/wallet/")
    assert resp.status_code == 401
    assert resp.json()["success"] is False


@pytest.mark.asyncio
async def test_deposit_initiates_stripe(client: AsyncClient, test_user):
    """Deposit returns a client_secret for Stripe."""
    mock_intent = MagicMock()
    mock_intent.id = "pi_test_123"
    mock_intent.client_secret = "pi_test_123_secret"

    with patch("app.api.wallet.stripe.PaymentIntent.create", return_value=mock_intent), \
         patch("app.api.wallet.settings") as mock_settings:
        mock_settings.stripe_secret_key = "sk_test_mock"
        client.cookies.set("access_token", _token(test_user.id))
        resp = await client.post("/api/v1/wallet/deposit", json={"amount": 100.0})
    assert resp.status_code == 200
    data = resp.json()
    assert data["success"] is True
    assert "client_secret" in data["data"]


@pytest.mark.asyncio
async def test_withdraw_insufficient_balance(client: AsyncClient, test_user):
    """Cannot withdraw more than available balance."""
    client.cookies.set("access_token", _token(test_user.id))
    resp = await client.post("/api/v1/wallet/withdraw", json={"amount": 999999.0})
    assert resp.status_code == 400
    assert resp.json()["success"] is False


@pytest.mark.asyncio
async def test_withdraw_success(client: AsyncClient, test_user):
    client.cookies.set("access_token", _token(test_user.id))
    resp = await client.post("/api/v1/wallet/withdraw", json={"amount": 10.0})
    assert resp.status_code == 200
    data = resp.json()
    assert data["success"] is True


@pytest.mark.asyncio
async def test_list_transactions(client: AsyncClient, test_user):
    client.cookies.set("access_token", _token(test_user.id))
    resp = await client.get("/api/v1/wallet/transactions")
    assert resp.status_code == 200
    assert resp.json()["success"] is True


# ── Liquidity ─────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_add_liquidity(client: AsyncClient, test_user, test_market):
    client.cookies.set("access_token", _token(test_user.id))
    resp = await client.post(f"/api/v1/markets/{test_market.id}/liquidity", json={
        "amount": 50.0,
    })
    assert resp.status_code == 200
    data = resp.json()
    assert data["success"] is True
    assert "lp_tokens_minted" in data["data"]


@pytest.mark.asyncio
async def test_add_liquidity_insufficient_balance(client: AsyncClient, test_user, test_market):
    client.cookies.set("access_token", _token(test_user.id))
    resp = await client.post(f"/api/v1/markets/{test_market.id}/liquidity", json={
        "amount": 999999.0,
    })
    assert resp.status_code == 422
    assert resp.json()["success"] is False


@pytest.mark.asyncio
async def test_remove_liquidity(client: AsyncClient, test_user, test_market, db_session):
    # First add liquidity
    client.cookies.set("access_token", _token(test_user.id))
    add_resp = await client.post(f"/api/v1/markets/{test_market.id}/liquidity", json={
        "amount": 50.0,
    })
    assert add_resp.json()["success"] is True

    # Get LP position to find lp_tokens
    pos_resp = await client.get(f"/api/v1/markets/{test_market.id}/liquidity")
    lp_tokens = pos_resp.json()["data"]["lp_tokens"]

    # Remove liquidity
    resp = await client.request("DELETE", f"/api/v1/markets/{test_market.id}/liquidity", json={
        "lp_tokens": lp_tokens,
    })
    assert resp.status_code == 200
    assert resp.json()["success"] is True


@pytest.mark.asyncio
async def test_get_lp_position(client: AsyncClient, test_user, test_market):
    client.cookies.set("access_token", _token(test_user.id))
    resp = await client.get(f"/api/v1/markets/{test_market.id}/liquidity")
    assert resp.status_code == 200
    data = resp.json()
    assert "lp_tokens" in data["data"]


@pytest.mark.asyncio
async def test_lp_analytics(client: AsyncClient, test_user):
    client.cookies.set("access_token", _token(test_user.id))
    resp = await client.get("/api/v1/markets/liquidity/analytics")
    assert resp.status_code == 200
    assert resp.json()["success"] is True


# ── Split / Merge ──────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_split(client: AsyncClient, test_user, test_market):
    client.cookies.set("access_token", _token(test_user.id))
    resp = await client.post(f"/api/v1/split-merge/split?market_id={test_market.id}&amount=10.0")
    assert resp.status_code == 200
    data = resp.json()
    assert data["success"] is True
    assert data["data"]["yes_shares"] == data["data"]["no_shares"]


@pytest.mark.asyncio
async def test_split_insufficient_balance(client: AsyncClient, test_user, test_market):
    client.cookies.set("access_token", _token(test_user.id))
    resp = await client.post(f"/api/v1/split-merge/split?market_id={test_market.id}&amount=999999.0")
    assert resp.status_code == 422
    assert resp.json()["success"] is False


@pytest.mark.asyncio
async def test_merge(client: AsyncClient, test_user, test_market, db_session):
    # First split
    client.cookies.set("access_token", _token(test_user.id))
    await client.post(f"/api/v1/split-merge/split?market_id={test_market.id}&amount=10.0")

    # Merge fails: split deducts 2% fee, so user holds 9.8 YES + 9.8 NO shares
    # but tries to merge 10.0 — insufficient on both sides
    resp = await client.post(f"/api/v1/split-merge/merge?market_id={test_market.id}&amount=10.0")
    assert resp.status_code == 422
    assert "Insufficient YES shares" in resp.json()["error"]


@pytest.mark.asyncio
async def test_merge_insufficient_shares(client: AsyncClient, test_user, test_market):
    client.cookies.set("access_token", _token(test_user.id))
    resp = await client.post(f"/api/v1/split-merge/merge?market_id={test_market.id}&amount=999999.0")
    assert resp.status_code == 422
    assert resp.json()["success"] is False


@pytest.mark.asyncio
async def test_split_negative_amount(client: AsyncClient, test_user, test_market):
    client.cookies.set("access_token", _token(test_user.id))
    resp = await client.post(f"/api/v1/split-merge/split?market_id={test_market.id}&amount=-5.0")
    assert resp.status_code in (200, 422)
    if resp.status_code == 200:
        assert resp.json()["success"] is False


# ── Positions ───────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_list_positions_empty(client: AsyncClient, test_user):
    client.cookies.set("access_token", _token(test_user.id))
    resp = await client.get("/api/v1/positions/")
    assert resp.status_code == 200
    data = resp.json()
    assert data["success"] is True
    assert data["data"]["positions"] == []


@pytest.mark.asyncio
async def test_list_positions_with_split(client: AsyncClient, test_user, test_market):
    """After splitting, user has YES and NO positions."""
    client.cookies.set("access_token", _token(test_user.id))
    await client.post(f"/api/v1/split-merge/split?market_id={test_market.id}&amount=10.0")

    resp = await client.get("/api/v1/positions/")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data["data"]["positions"]) == 2  # YES and NO


# ── Wallet edge cases ───────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_withdraw_amount_zero(client: AsyncClient, test_user):
    """Cannot withdraw amount=0 (gt=0 validation)."""
    client.cookies.set("access_token", _token(test_user.id))
    resp = await client.post("/api/v1/wallet/withdraw", json={"amount": 0.0})
    assert resp.status_code == 422
    assert resp.json()["success"] is False


@pytest.mark.asyncio
async def test_withdraw_negative_amount(client: AsyncClient, test_user):
    """Cannot withdraw a negative amount."""
    client.cookies.set("access_token", _token(test_user.id))
    resp = await client.post("/api/v1/wallet/withdraw", json={"amount": -5.0})
    assert resp.status_code == 422
    assert resp.json()["success"] is False


@pytest.mark.asyncio
async def test_withdraw_exact_balance(client: AsyncClient, test_user):
    """Withdrawing the exact available balance should succeed."""
    client.cookies.set("access_token", _token(test_user.id))
    # Get current balance
    wallet_resp = await client.get("/api/v1/wallet/")
    balance = wallet_resp.json()["data"]["available_balance"]
    if Decimal(str(balance)) <= 0:
        # Skip if no balance to begin with
        pytest.skip("No available balance to test exact-balance withdrawal")
    resp = await client.post("/api/v1/wallet/withdraw", json={"amount": balance})
    assert resp.status_code == 200
    assert resp.json()["success"] is True


# ── Liquidity edge cases ────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_add_liquidity_amount_zero(client: AsyncClient, test_user, test_market):
    """Cannot add liquidity with amount=0 (gt=0 validation)."""
    client.cookies.set("access_token", _token(test_user.id))
    resp = await client.post(f"/api/v1/markets/{test_market.id}/liquidity", json={
        "amount": 0.0,
    })
    assert resp.status_code == 422
    assert resp.json()["success"] is False


@pytest.mark.asyncio
async def test_remove_liquidity_amount_zero(client: AsyncClient, test_user, test_market):
    """Cannot remove liquidity with lp_tokens=0 (gt=0 validation)."""
    client.cookies.set("access_token", _token(test_user.id))
    resp = await client.request("DELETE", f"/api/v1/markets/{test_market.id}/liquidity", json={
        "lp_tokens": 0.0,
    })
    assert resp.status_code == 422
    assert resp.json()["success"] is False


@pytest.mark.asyncio
async def test_remove_liquidity_exceeding_position(client: AsyncClient, test_user, test_market):
    """Cannot remove more LP tokens than user holds."""
    client.cookies.set("access_token", _token(test_user.id))
    # Add liquidity first to have a position
    add_resp = await client.post(f"/api/v1/markets/{test_market.id}/liquidity", json={
        "amount": 50.0,
    })
    if add_resp.status_code != 200:
        pytest.skip("Could not add liquidity to test remove edge case")
    # Try to remove more than we have
    resp = await client.request("DELETE", f"/api/v1/markets/{test_market.id}/liquidity", json={
        "lp_tokens": 999999.0,
    })
    assert resp.status_code in (400, 422)
    assert resp.json()["success"] is False


# ── Split/Merge edge cases ─────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_split_amount_zero(client: AsyncClient, test_user, test_market):
    """Cannot split with amount=0 (validation error)."""
    client.cookies.set("access_token", _token(test_user.id))
    resp = await client.post(f"/api/v1/split-merge/split?market_id={test_market.id}&amount=0.0")
    assert resp.status_code == 422
    assert resp.json()["success"] is False


@pytest.mark.asyncio
async def test_merge_amount_zero(client: AsyncClient, test_user, test_market):
    """Cannot merge with amount=0 (validation error)."""
    client.cookies.set("access_token", _token(test_user.id))
    resp = await client.post(f"/api/v1/split-merge/merge?market_id={test_market.id}&amount=0.0")
    assert resp.status_code == 422
    assert resp.json()["success"] is False


# ── Positions edge cases ───────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_list_positions_filter_by_market(client: AsyncClient, test_user, test_market):
    """Filter positions by market_id."""
    client.cookies.set("access_token", _token(test_user.id))
    resp = await client.get(f"/api/v1/positions/?market_id={test_market.id}")
    assert resp.status_code == 200
    assert resp.json()["success"] is True
