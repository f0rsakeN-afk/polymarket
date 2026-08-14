"""Tests for webhook endpoints."""
import hashlib
import hmac
import json
import time
from decimal import Decimal
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest
from httpx import AsyncClient


def _stripe_signature(payload: bytes, secret: str) -> str:
    """Compute Stripe webhook signature (mock implementation matching Stripe format)."""
    timestamp = int(time.time())
    signed_payload = f"{timestamp}." + payload.decode()
    signature = hmac.new(secret.encode(), signed_payload.encode(), hashlib.sha256).hexdigest()
    return f"t={timestamp},v1={signature}"


# ── Stripe webhook ─────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_stripe_webhook_payment_intent_succeeded(client: AsyncClient, test_user, db_session):
    """Stripe webhook credits wallet on successful payment."""
    from app.models.wallet import Wallet, Transaction

    payment_intent_id = f"pi_test_{uuid4().hex[:8]}"
    amount_cents = 5000  # $50.00

    payload = {
        "type": "payment_intent.succeeded",
        "data": {
            "object": {
                "id": payment_intent_id,
                "amount": amount_cents,
                "currency": "usd",
                "metadata": {"user_id": str(test_user.id)},
            }
        },
    }

    with patch("app.api.webhooks.verify_stripe_signature", return_value=True):
        resp = await client.post(
            "/api/v1/webhooks/stripe",
            json=payload,
            headers={"stripe-signature": "test_sig"},
        )

    assert resp.status_code == 200
    data = resp.json()
    assert data["success"] is True
    assert data["data"]["status"] == "credited"


@pytest.mark.asyncio
async def test_stripe_webhook_idempotent(client: AsyncClient, test_user, db_session):
    """Stripe webhook is idempotent — same payment_intent doesn't double-credit."""
    from app.models.wallet import Wallet, Transaction

    payment_intent_id = f"pi_test_{uuid4().hex[:8]}"
    amount_cents = 5000

    # Get initial balance
    from sqlalchemy import select
    result = await db_session.execute(select(Wallet).where(Wallet.user_id == test_user.id))
    wallet_before = result.scalar_one_or_none()
    initial_balance = wallet_before.balance

    payload = {
        "type": "payment_intent.succeeded",
        "data": {
            "object": {
                "id": payment_intent_id,
                "amount": amount_cents,
                "currency": "usd",
                "metadata": {"user_id": str(test_user.id)},
            }
        },
    }

    with patch("app.api.webhooks.verify_stripe_signature", return_value=True):
        # First call — should credit
        resp1 = await client.post("/api/v1/webhooks/stripe", json=payload, headers={"stripe-signature": "sig1"})
        assert resp1.json()["data"]["status"] == "credited"

        # Second call — should be ignored (already processed)
        resp2 = await client.post("/api/v1/webhooks/stripe", json=payload, headers={"stripe-signature": "sig2"})
        assert resp2.json()["data"]["status"] == "already_processed"

    # Balance only increased once
    await db_session.refresh(wallet_before)
    expected = Decimal("50.00")  # amount_cents / 100
    assert wallet_before.balance == initial_balance + expected


@pytest.mark.asyncio
async def test_stripe_webhook_no_user_id(client: AsyncClient, db_session):
    """Stripe webhook ignores event with no user_id in metadata."""
    payload = {
        "type": "payment_intent.succeeded",
        "data": {
            "object": {
                "id": f"pi_test_{uuid4().hex[:8]}",
                "amount": 5000,
                "currency": "usd",
                "metadata": {},  # no user_id
            }
        },
    }

    with patch("app.api.webhooks.verify_stripe_signature", return_value=True):
        resp = await client.post("/api/v1/webhooks/stripe", json=payload)
    assert resp.status_code == 200
    assert resp.json()["data"]["status"] == "ignored"


@pytest.mark.asyncio
async def test_stripe_webhook_payment_failed(client: AsyncClient, db_session):
    """Stripe webhook handles failed payment gracefully."""
    payload = {
        "type": "payment_intent.payment_failed",
        "data": {
            "object": {
                "id": f"pi_failed_{uuid4().hex[:8]}",
                "amount": 5000,
                "currency": "usd",
                "metadata": {},
            }
        },
    }

    with patch("app.api.webhooks.verify_stripe_signature", return_value=True):
        resp = await client.post("/api/v1/webhooks/stripe", json=payload)
    assert resp.status_code == 200
    assert resp.json()["data"]["status"] == "payment_failed"


@pytest.mark.asyncio
async def test_stripe_webhook_unhandled_event(client: AsyncClient, db_session):
    """Stripe webhook returns unhandled for unknown event types."""
    payload = {"type": "customer.created", "data": {"object": {}}}

    with patch("app.api.webhooks.verify_stripe_signature", return_value=True):
        resp = await client.post("/api/v1/webhooks/stripe", json=payload)
    assert resp.status_code == 200
    assert resp.json()["data"]["status"] == "unhandled_event_type"


@pytest.mark.asyncio
async def test_stripe_webhook_invalid_signature(client: AsyncClient, db_session):
    """Stripe webhook rejects invalid signature."""
    payload = {
        "type": "payment_intent.succeeded",
        "data": {
            "object": {
                "id": f"pi_test_{uuid4().hex[:8]}",
                "amount": 5000,
                "currency": "usd",
                "metadata": {},
            }
        },
    }
    with patch("app.api.webhooks.verify_stripe_signature", return_value=False):
        resp = await client.post(
            "/api/v1/webhooks/stripe",
            json=payload,
            headers={"stripe-signature": "bad_sig"},
        )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_stripe_webhook_missing_amount(client: AsyncClient, db_session):
    """Stripe webhook handles missing amount gracefully (uses 0)."""
    payload = {
        "type": "payment_intent.succeeded",
        "data": {
            "object": {
                "id": f"pi_test_{uuid4().hex[:8]}",
                # no "amount" key
                "currency": "usd",
                "metadata": {},
            }
        },
    }
    with patch("app.api.webhooks.verify_stripe_signature", return_value=True):
        resp = await client.post("/api/v1/webhooks/stripe", json=payload)
    assert resp.status_code == 200
    assert resp.json()["data"]["status"] == "ignored"  # no user_id either


@pytest.mark.asyncio
async def test_stripe_webhook_zero_amount(client: AsyncClient, test_user, db_session):
    """Stripe webhook credits $0 when amount is 0."""
    from app.models.wallet import Wallet
    from sqlalchemy import select

    payment_intent_id = f"pi_test_{uuid4().hex[:8]}"

    result = await db_session.execute(select(Wallet).where(Wallet.user_id == test_user.id))
    wallet_before = result.scalar_one_or_none()
    initial_balance = wallet_before.balance

    payload = {
        "type": "payment_intent.succeeded",
        "data": {
            "object": {
                "id": payment_intent_id,
                "amount": 0,
                "currency": "usd",
                "metadata": {"user_id": str(test_user.id)},
            }
        },
    }

    with patch("app.api.webhooks.verify_stripe_signature", return_value=True):
        resp = await client.post("/api/v1/webhooks/stripe", json=payload, headers={"stripe-signature": "sig"})

    assert resp.status_code == 200
    assert resp.json()["data"]["status"] == "credited"

    await db_session.refresh(wallet_before)
    assert wallet_before.balance == initial_balance  # $0 credited, balance unchanged


@pytest.mark.asyncio
async def test_stripe_webhook_wallet_not_found(client: AsyncClient, db_session):
    """Stripe webhook handles wallet not found gracefully."""
    payment_intent_id = f"pi_test_{uuid4().hex[:8]}"
    payload = {
        "type": "payment_intent.succeeded",
        "data": {
            "object": {
                "id": payment_intent_id,
                "amount": 5000,
                "currency": "usd",
                "metadata": {"user_id": str(uuid4())},  # user without wallet
            }
        },
    }
    with patch("app.api.webhooks.verify_stripe_signature", return_value=True):
        resp = await client.post("/api/v1/webhooks/stripe", json=payload)
    assert resp.status_code == 200
    assert resp.json()["data"]["status"] == "wallet_not_found"


@pytest.mark.asyncio
async def test_stripe_webhook_invalid_json(client: AsyncClient, db_session):
    """Stripe webhook rejects non-JSON payload."""
    with patch("app.api.webhooks.verify_stripe_signature", return_value=True):
        resp = await client.post(
            "/api/v1/webhooks/stripe",
            content=b"not json",
            headers={"content-type": "application/json"},
        )
    assert resp.status_code == 422
