"""Tests for wallet, liquidity, split/merge, and position endpoints."""
import asyncio
import uuid
from decimal import Decimal
from unittest.mock import MagicMock, patch

import pytest
from conftest import TestSessionFactory, create_login_session, token_for
from httpx import AsyncClient
from sqlalchemy import select

from app.models.wallet import Wallet
from app.services.wallet_service import WalletService

# ── Wallet ─────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_get_wallet(client: AsyncClient, test_user):
    client.cookies.set("access_token", token_for(test_user.id))
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
async def test_wallet_provisioned_when_missing(client: AsyncClient, db_session):
    """A user with no wallet row gets one, not a 404.

    Registration creates the wallet, so this state means the invariant broke
    upstream - a user predating that code, or a signup that half-committed.

    It used to 404, and that was wrong twice: the status was a lie (this is the
    caller's *own* wallet, not a missing resource), and the client turned the
    null result into "Not authenticated" - so a signed-in user was told to log in
    again for a problem logging in could not fix.

    The gap survived because every fixture in this suite creates a wallet up
    front. This one deliberately does not, which is the only way to reach it.
    """
    import uuid

    from sqlalchemy import select

    from app.deps import hash_password
    from app.models.user import User
    from app.models.wallet import Wallet

    uid = uuid.uuid4().hex[:8]
    user = User(
        email=f"nowallet_{uid}@example.com",
        username=f"nowallet_{uid}",
        password_hash=hash_password("NoWallet!Pass1"),
        is_email_verified=True,
        is_active=True,
    )
    db_session.add(user)
    # flush first: the UUID is generated on insert, and the session row needs it.
    await db_session.flush()
    await create_login_session(db_session, user)
    await db_session.commit()
    await db_session.refresh(user)

    # Confirm the precondition: no wallet exists for this user.
    existing = await db_session.execute(select(Wallet).where(Wallet.user_id == user.id))
    assert existing.scalar_one_or_none() is None, "fixture precondition failed"

    client.cookies.set("access_token", token_for(user.id))
    resp = await client.get("/api/v1/wallet/")

    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["success"] is True
    # A zero wallet, not an error - the user can now deposit.
    assert Decimal(data["data"]["balance"]) == Decimal(0)
    assert Decimal(data["data"]["available_balance"]) == Decimal(0)
    assert data["data"]["currency"] == "USDC"

    # And it is a real, persisted row, so the next read is an ordinary read.
    now_exists = await db_session.execute(select(Wallet).where(Wallet.user_id == user.id))
    assert now_exists.scalar_one_or_none() is not None

    again = await client.get("/api/v1/wallet/")
    assert again.status_code == 200
    assert again.json()["data"] == data["data"]


@pytest.mark.asyncio
async def test_wallet_provisioning_survives_concurrent_first_reads(db_session):
    """Two simultaneous first-reads must not surface as a 500.

    `Wallet.user_id` is unique, so whichever request loses the race on insert gets
    an IntegrityError. The loser wants the same wallet the winner just created, so
    it re-reads rather than propagating - otherwise a wallet page load 500s
    exactly when the system is least able to explain why.

    Each caller gets its own session, because that is what production does - one
    session per request. Sharing a single session between concurrent coroutines
    would not exercise the race at all: the second commit would fail on session
    state, not on the unique constraint, which is a different failure that proves
    nothing about this code.
    """
    uid = uuid.uuid4().hex[:8]
    user = await _user_without_wallet(db_session, uid)

    async def provision():
        async with TestSessionFactory() as session:
            return await WalletService.get_or_create_wallet(session, user.id)

    results = await asyncio.gather(provision(), provision(), return_exceptions=True)

    errors = [r for r in results if isinstance(r, Exception)]
    assert not errors, f"concurrent provisioning raised: {errors}"
    assert len({r.id for r in results}) == 1, "concurrent calls produced different wallets"

    # Exactly one wallet row, not two.
    rows = await db_session.execute(select(Wallet).where(Wallet.user_id == user.id))
    assert len(rows.scalars().all()) == 1


async def _user_without_wallet(db_session, uid: str):
    from app.deps import hash_password
    from app.models.user import User

    user = User(
        email=f"concurrent_{uid}@example.com",
        username=f"concurrent_{uid}",
        password_hash=hash_password("Concurrent!Pass1"),
        is_email_verified=True,
        is_active=True,
    )
    db_session.add(user)
    # flush first: the UUID is generated on insert, and the session row needs it.
    await db_session.flush()
    await create_login_session(db_session, user)
    await db_session.commit()
    await db_session.refresh(user)
    return user


@pytest.mark.asyncio
async def test_deposit_initiates_stripe(client: AsyncClient, test_user, monkeypatch):
    """Deposit returns a client_secret for Stripe."""
    from app.config import settings as app_settings

    mock_intent = MagicMock()
    mock_intent.id = "pi_test_123"
    mock_intent.client_secret = "pi_test_123_secret"

    # Patch only the configured key: replacing the whole settings object would
    # turn max_deposit and friends into MagicMocks and break their comparisons.
    monkeypatch.setattr(app_settings, "stripe_secret_key", "sk_test_mock")
    with patch("app.api.wallet.stripe.PaymentIntent.create", return_value=mock_intent):
        client.cookies.set("access_token", token_for(test_user.id))
        resp = await client.post("/api/v1/wallet/deposit", json={"amount": 100.0})
    assert resp.status_code == 200
    data = resp.json()
    assert data["success"] is True
    assert "client_secret" in data["data"]


@pytest.mark.asyncio
async def test_withdraw_insufficient_balance(client: AsyncClient, test_user):
    """More than the balance (but within max_withdrawal) → INSUFFICIENT_BALANCE."""
    client.cookies.set("access_token", token_for(test_user.id))
    # test_user holds 1000; settings.max_withdrawal is 10000, so this isolates
    # the balance check rather than tripping the withdrawal-limit check.
    resp = await client.post("/api/v1/wallet/withdraw", json={"amount": 5000.0})
    assert resp.status_code == 400
    assert resp.json()["success"] is False
    assert resp.json()["error_code"] == "INSUFFICIENT_BALANCE"


@pytest.mark.asyncio
async def test_withdraw_exceeds_max_limit(client: AsyncClient, admin_user):
    """Beyond settings.max_withdrawal → rejected as a validation error."""
    client.cookies.set("access_token", token_for(admin_user.id))
    resp = await client.post("/api/v1/wallet/withdraw", json={"amount": 999999.0})
    assert resp.status_code == 422
    assert resp.json()["success"] is False
    assert "exceeds maximum" in resp.json()["error"]


@pytest.mark.asyncio
async def test_withdraw_success(client: AsyncClient, test_user):
    client.cookies.set("access_token", token_for(test_user.id))
    resp = await client.post("/api/v1/wallet/withdraw", json={"amount": 10.0})
    assert resp.status_code == 200
    data = resp.json()
    assert data["success"] is True


@pytest.mark.asyncio
async def test_list_transactions(client: AsyncClient, test_user):
    client.cookies.set("access_token", token_for(test_user.id))
    resp = await client.get("/api/v1/wallet/transactions")
    assert resp.status_code == 200
    assert resp.json()["success"] is True


# ── Liquidity ─────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_add_liquidity(client: AsyncClient, test_user, test_market):
    client.cookies.set("access_token", token_for(test_user.id))
    resp = await client.post(f"/api/v1/markets/{test_market.id}/liquidity", json={
        "amount": 50.0,
    })
    assert resp.status_code == 200
    data = resp.json()
    assert data["success"] is True
    assert "lp_tokens_minted" in data["data"]


@pytest.mark.asyncio
async def test_add_liquidity_insufficient_balance(client: AsyncClient, test_user, test_market):
    client.cookies.set("access_token", token_for(test_user.id))
    resp = await client.post(f"/api/v1/markets/{test_market.id}/liquidity", json={
        "amount": 999999.0,
    })
    assert resp.status_code == 422
    assert resp.json()["success"] is False


@pytest.mark.asyncio
async def test_remove_liquidity(client: AsyncClient, test_user, test_market, db_session):
    # First add liquidity
    client.cookies.set("access_token", token_for(test_user.id))
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
    client.cookies.set("access_token", token_for(test_user.id))
    resp = await client.get(f"/api/v1/markets/{test_market.id}/liquidity")
    assert resp.status_code == 200
    data = resp.json()
    assert "lp_tokens" in data["data"]


@pytest.mark.asyncio
async def test_lp_analytics(client: AsyncClient, test_user):
    client.cookies.set("access_token", token_for(test_user.id))
    resp = await client.get("/api/v1/markets/liquidity/analytics")
    assert resp.status_code == 200
    assert resp.json()["success"] is True


# ── Split / Merge ──────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_split(client: AsyncClient, test_user, test_market):
    client.cookies.set("access_token", token_for(test_user.id))
    resp = await client.post("/api/v1/split-merge/split", json={"market_id": str(test_market.id), "amount": 10.0})
    assert resp.status_code == 200
    data = resp.json()
    assert data["success"] is True
    assert data["data"]["yes_shares"] == data["data"]["no_shares"]


@pytest.mark.asyncio
async def test_split_insufficient_balance(client: AsyncClient, test_user, test_market):
    client.cookies.set("access_token", token_for(test_user.id))
    resp = await client.post("/api/v1/split-merge/split", json={"market_id": str(test_market.id), "amount": 999999.0})
    assert resp.status_code == 422
    assert resp.json()["success"] is False


@pytest.mark.asyncio
async def test_merge(client: AsyncClient, test_user, test_market, db_session):
    # First split
    client.cookies.set("access_token", token_for(test_user.id))
    await client.post("/api/v1/split-merge/split", json={"market_id": str(test_market.id), "amount": 10.0})

    # Merge fails: split deducts 2% fee, so user holds 9.8 YES + 9.8 NO shares
    # but tries to merge 10.0 • insufficient on both sides
    resp = await client.post("/api/v1/split-merge/merge", json={"market_id": str(test_market.id), "amount": 10.0})
    assert resp.status_code == 422
    assert "Insufficient YES shares" in resp.json()["error"]


@pytest.mark.asyncio
async def test_merge_insufficient_shares(client: AsyncClient, test_user, test_market):
    client.cookies.set("access_token", token_for(test_user.id))
    resp = await client.post("/api/v1/split-merge/merge", json={"market_id": str(test_market.id), "amount": 999999.0})
    assert resp.status_code == 422
    assert resp.json()["success"] is False


@pytest.mark.asyncio
async def test_split_negative_amount(client: AsyncClient, test_user, test_market):
    client.cookies.set("access_token", token_for(test_user.id))
    resp = await client.post("/api/v1/split-merge/split", json={"market_id": str(test_market.id), "amount": -5.0})
    assert resp.status_code in (200, 422)
    if resp.status_code == 200:
        assert resp.json()["success"] is False


# ── Positions ───────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_list_positions_empty(client: AsyncClient, test_user):
    client.cookies.set("access_token", token_for(test_user.id))
    resp = await client.get("/api/v1/positions/")
    assert resp.status_code == 200
    data = resp.json()
    assert data["success"] is True
    assert data["data"]["positions"] == []


@pytest.mark.asyncio
async def test_list_positions_with_split(client: AsyncClient, test_user, test_market):
    """After splitting, user has YES and NO positions."""
    client.cookies.set("access_token", token_for(test_user.id))
    await client.post("/api/v1/split-merge/split", json={"market_id": str(test_market.id), "amount": 10.0})

    resp = await client.get("/api/v1/positions/")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data["data"]["positions"]) == 2  # YES and NO


# ── Wallet edge cases ───────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_withdraw_amount_zero(client: AsyncClient, test_user):
    """Cannot withdraw amount=0 (gt=0 validation)."""
    client.cookies.set("access_token", token_for(test_user.id))
    resp = await client.post("/api/v1/wallet/withdraw", json={"amount": 0.0})
    assert resp.status_code == 422
    assert resp.json()["success"] is False


@pytest.mark.asyncio
async def test_withdraw_negative_amount(client: AsyncClient, test_user):
    """Cannot withdraw a negative amount."""
    client.cookies.set("access_token", token_for(test_user.id))
    resp = await client.post("/api/v1/wallet/withdraw", json={"amount": -5.0})
    assert resp.status_code == 422
    assert resp.json()["success"] is False


@pytest.mark.asyncio
async def test_withdraw_exact_balance(client: AsyncClient, test_user):
    """Withdrawing the exact available balance should succeed."""
    client.cookies.set("access_token", token_for(test_user.id))
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
    client.cookies.set("access_token", token_for(test_user.id))
    resp = await client.post(f"/api/v1/markets/{test_market.id}/liquidity", json={
        "amount": 0.0,
    })
    assert resp.status_code == 422
    assert resp.json()["success"] is False


@pytest.mark.asyncio
async def test_remove_liquidity_amount_zero(client: AsyncClient, test_user, test_market):
    """Cannot remove liquidity with lp_tokens=0 (gt=0 validation)."""
    client.cookies.set("access_token", token_for(test_user.id))
    resp = await client.request("DELETE", f"/api/v1/markets/{test_market.id}/liquidity", json={
        "lp_tokens": 0.0,
    })
    assert resp.status_code == 422
    assert resp.json()["success"] is False


@pytest.mark.asyncio
async def test_remove_liquidity_exceeding_position(client: AsyncClient, test_user, test_market):
    """Cannot remove more LP tokens than user holds."""
    client.cookies.set("access_token", token_for(test_user.id))
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
    client.cookies.set("access_token", token_for(test_user.id))
    resp = await client.post("/api/v1/split-merge/split", json={"market_id": str(test_market.id), "amount": 0.0})
    assert resp.status_code == 422
    assert resp.json()["success"] is False


@pytest.mark.asyncio
async def test_merge_amount_zero(client: AsyncClient, test_user, test_market):
    """Cannot merge with amount=0 (validation error)."""
    client.cookies.set("access_token", token_for(test_user.id))
    resp = await client.post("/api/v1/split-merge/merge", json={"market_id": str(test_market.id), "amount": 0.0})
    assert resp.status_code == 422
    assert resp.json()["success"] is False


# ── Positions edge cases ───────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_list_positions_filter_by_market(client: AsyncClient, test_user, test_market):
    """Filter positions by market_id."""
    client.cookies.set("access_token", token_for(test_user.id))
    resp = await client.get(f"/api/v1/positions/?market_id={test_market.id}")
    assert resp.status_code == 200
    assert resp.json()["success"] is True
