"""Tests for the Stripe webhook.

These exercise the *real* signature verification path: every request is signed
with ``settings.stripe_webhook_secret`` over the exact bytes on the wire, so
the HMAC check, the replay window and the fail-closed behaviour are all
covered without mocking the verifier.
"""
import hashlib
import hmac
import json
import time
from decimal import Decimal
from uuid import uuid4

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from app.config import settings
from app.models.wallet import Wallet

# ── Helpers ───────────────────────────────────────────────────────────────────

def _sign(payload: bytes, *, secret: str | None = None, age: int = 0) -> dict[str, str]:
    """Build a ``stripe-signature`` header the way Stripe computes it."""
    if secret is None:
        secret = settings.stripe_webhook_secret
    timestamp = int(time.time()) - age
    mac = hmac.new(secret.encode(), f"{timestamp}.".encode() + payload, hashlib.sha256)
    return {"stripe-signature": f"t={timestamp},v1={mac.hexdigest()}"}


async def _deliver(
    client: AsyncClient,
    payload,
    *,
    secret: str | None = None,
    age: int = 0,
    signed: bool = True,
):
    """POST a webhook delivery, signing the exact bytes that go on the wire."""
    body = payload if isinstance(payload, bytes) else json.dumps(payload).encode()
    headers = {"content-type": "application/json"}
    if signed:
        headers.update(_sign(body, secret=secret, age=age))
    return await client.post("/api/v1/webhooks/stripe", content=body, headers=headers)


async def _balance(db_session, user) -> Decimal:
    # Column-level read: goes to the DB instead of the identity map, so it sees
    # the webhook's committed credit regardless of session instance state.
    return (
        await db_session.execute(select(Wallet.balance).where(Wallet.user_id == user.id))
    ).scalar_one()


def _payment_succeeded(user_id: str, *, amount: int = 5000, payment_intent: str | None = None) -> dict:
    return {
        "id": f"evt_{uuid4().hex[:12]}",
        "object": "event",
        "type": "payment_intent.succeeded",
        "data": {
            "object": {
                "id": payment_intent or f"pi_test_{uuid4().hex[:8]}",
                "object": "payment_intent",
                "amount": amount,
                "currency": "usd",
                "metadata": {"user_id": user_id},
            }
        },
    }


# ── Happy paths ───────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_stripe_webhook_payment_intent_succeeded(client: AsyncClient, test_user, db_session):
    """A correctly signed payment_intent.succeeded credits the wallet."""
    before = await _balance(db_session, test_user)

    resp = await _deliver(client, _payment_succeeded(str(test_user.id)))

    assert resp.status_code == 200
    data = resp.json()
    assert data["success"] is True
    assert data["data"]["status"] == "credited"
    assert data["data"]["transaction_id"]
    assert await _balance(db_session, test_user) == before + Decimal("50.00")


@pytest.mark.asyncio
async def test_stripe_webhook_idempotent(client: AsyncClient, test_user, db_session):
    """Redelivering the same payment intent does not double-credit."""
    event = _payment_succeeded(str(test_user.id))
    before = await _balance(db_session, test_user)

    resp1 = await _deliver(client, event)
    assert resp1.json()["data"]["status"] == "credited"

    # Stripe redelivers: same event bytes, fresh signature.
    resp2 = await _deliver(client, event)
    assert resp2.status_code == 200
    assert resp2.json()["data"]["status"] == "already_processed"

    assert await _balance(db_session, test_user) == before + Decimal("50.00")


@pytest.mark.asyncio
async def test_stripe_webhook_no_user_id(client: AsyncClient, db_session):
    """Events without a user_id in metadata are acknowledged but ignored."""
    event = {
        "object": "event",
        "type": "payment_intent.succeeded",
        "data": {"object": {"id": f"pi_{uuid4().hex[:8]}", "amount": 5000, "metadata": {}}},
    }

    resp = await _deliver(client, event)

    assert resp.status_code == 200
    assert resp.json()["data"]["status"] == "ignored"


@pytest.mark.asyncio
async def test_stripe_webhook_payment_failed(client: AsyncClient, db_session):
    resp = await _deliver(
        client,
        {
            "object": "event",
            "type": "payment_intent.payment_failed",
            "data": {"object": {"id": f"pi_failed_{uuid4().hex[:8]}", "amount": 5000, "metadata": {}}},
        },
    )
    assert resp.status_code == 200
    assert resp.json()["data"]["status"] == "payment_failed"


@pytest.mark.asyncio
async def test_stripe_webhook_unhandled_event(client: AsyncClient, db_session):
    resp = await _deliver(client, {"object": "event", "type": "customer.created", "data": {"object": {}}})
    assert resp.status_code == 200
    assert resp.json()["data"]["status"] == "unhandled_event_type"


@pytest.mark.asyncio
async def test_stripe_webhook_non_usd_currency_ignored(client: AsyncClient, test_user, db_session):
    """A non-USD charge must never credit a USDC wallet."""
    event = _payment_succeeded(str(test_user.id))
    event["data"]["object"]["currency"] = "eur"

    resp = await _deliver(client, event)

    assert resp.status_code == 200
    assert resp.json()["data"]["status"] == "ignored_currency"


@pytest.mark.asyncio
async def test_stripe_webhook_zero_amount(client: AsyncClient, test_user, db_session):
    """amount=0 still records the deposit but credits nothing."""
    before = await _balance(db_session, test_user)

    resp = await _deliver(client, _payment_succeeded(str(test_user.id), amount=0))

    assert resp.status_code == 200
    assert resp.json()["data"]["status"] == "credited"
    assert await _balance(db_session, test_user) == before


@pytest.mark.asyncio
async def test_stripe_webhook_wallet_not_found(client: AsyncClient, db_session):
    """500 (not 200) so Stripe retries instead of silently dropping the event."""
    resp = await _deliver(client, _payment_succeeded(str(uuid4())))

    assert resp.status_code == 500
    assert resp.json()["success"] is False


# ── Signature / authentication edge cases ─────────────────────────────────────

@pytest.mark.asyncio
async def test_stripe_webhook_invalid_signature(client: AsyncClient, test_user, db_session):
    """Signed with the wrong secret → 401, wallet untouched."""
    before = await _balance(db_session, test_user)
    event = _payment_succeeded(str(test_user.id))

    resp = await _deliver(client, event, secret="whsec_wrong_secret")

    assert resp.status_code == 401
    assert resp.json()["success"] is False
    assert await _balance(db_session, test_user) == before


@pytest.mark.asyncio
async def test_stripe_webhook_missing_signature_header(client: AsyncClient, test_user, db_session):
    resp = await _deliver(client, _payment_succeeded(str(test_user.id)), signed=False)
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_stripe_webhook_stale_timestamp_rejected(client: AsyncClient, test_user, db_session):
    """A captured request replayed beyond the tolerance window → 401."""
    # STRIPE_TOLERANCE is 300s; sign with a timestamp far outside it.
    resp = await _deliver(client, _payment_succeeded(str(test_user.id)), age=360)
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_stripe_webhook_tampered_payload(client: AsyncClient, test_user, db_session):
    """Signature over one body, different body delivered → 401."""
    signed_body = json.dumps(_payment_succeeded(str(test_user.id))).encode()
    tampered = json.dumps(_payment_succeeded(str(test_user.id), amount=5_000_000)).encode()

    resp = await client.post(
        "/api/v1/webhooks/stripe",
        content=tampered,
        headers={"content-type": "application/json", **_sign(signed_body)},
    )
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_stripe_webhook_unconfigured_secret_fails_closed(
    client: AsyncClient, test_user, db_session, monkeypatch
):
    """No secret configured → reject everything rather than accept everything."""
    monkeypatch.setattr(settings, "stripe_webhook_secret", "")
    resp = await _deliver(client, _payment_succeeded(str(test_user.id)))
    assert resp.status_code == 401


# ── Authenticated but malformed body → 422, not 401 ──────────────────────────

@pytest.mark.asyncio
async def test_stripe_webhook_invalid_json(client: AsyncClient, test_user, db_session):
    """A correctly signed body that isn't a JSON event is a 422."""
    resp = await _deliver(client, b"not json")
    assert resp.status_code == 422
    assert resp.json()["error_code"] == "INVALID_WEBHOOK_PAYLOAD"
