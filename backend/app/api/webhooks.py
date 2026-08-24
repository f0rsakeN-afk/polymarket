import hashlib
import hmac
import json
import logging
import time
from decimal import Decimal

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.exceptions import ValidationError
from app.api.responses import success_response
from app.config import settings
from app.database import get_db
from app.models.wallet import Transaction, Wallet

logger = logging.getLogger("polymarket")
router = APIRouter(prefix="/webhooks", tags=["webhooks"])

STRIPE_TOLERANCE = 300  # 5 minutes


async def verify_stripe_signature(payload: bytes, sig: str, secret: str) -> bool:
    """Verify Stripe webhook signature using HMAC."""
    if not secret:
        raise ValueError("STRIPE_WEBHOOK_SECRET is not configured — rejecting webhook")

    try:
        # Parse signature header: "t=timestamp,v1=signature"
        parts = dict(p.split("=", 1) for p in sig.split(","))
        timestamp = parts.get("t", "")
        v1_signature = parts.get("v1", "")

        if not timestamp or not v1_signature:
            return False

        # Check timestamp is within tolerance
        if abs(time.time() - int(timestamp)) > STRIPE_TOLERANCE:
            logger.warning(f"Stripe webhook timestamp outside tolerance: {timestamp}")
            return False

        # Compute expected signature
        signed_payload = f"{timestamp}.{payload.decode()}"
        expected = hmac.new(
            secret.encode(),
            signed_payload.encode(),
            hashlib.sha256,
        ).hexdigest()

        return hmac.compare_digest(expected, v1_signature)
    except Exception as e:
        logger.error(f"Stripe signature verification error: {e}")
        return False


@router.post("/stripe", summary="Stripe webhook", description="Handle Stripe webhook events. Currently processes payment_intent.succeeded to credit user wallets idempotently.")
async def stripe_webhook(
    request: Request,
    stripe_signature: str = Header(None),
    db: AsyncSession = Depends(get_db),
):
    payload = await request.body()

    if not await verify_stripe_signature(payload, stripe_signature or "", settings.stripe_webhook_secret):
        raise HTTPException(status_code=401, detail="Invalid Stripe signature")

    try:
        event = json.loads(payload)
    except json.JSONDecodeError:
        raise ValidationError("Invalid JSON payload")

    event_type = event.get("type", "")
    data = event.get("data", {}).get("object", {})

    if event_type == "payment_intent.succeeded":
        payment_intent_id = data.get("id", "")
        amount_cents = data.get("amount", 0)
        data.get("currency", "usd")
        metadata = data.get("metadata", {})

        user_id = metadata.get("user_id")
        if not user_id:
            logger.warning(f"Stripe webhook: no user_id in metadata for PI {payment_intent_id}")
            return success_response({"status": "ignored"})

        # Credit wallet — lock row to prevent concurrent webhook double-credit
        wallet_result = await db.execute(
            select(Wallet).where(Wallet.user_id == user_id).with_for_update()
        )
        wallet = wallet_result.scalar_one_or_none()
        if not wallet:
            # Return 500 so Stripe retries — the wallet should exist for any active user
            logger.error(f"Wallet not found for user {user_id}")
            raise HTTPException(status_code=500, detail="Wallet not found, will retry")

        amount = Decimal(str(amount_cents)) / 100  # cents to dollars

        # Build transaction record BEFORE updating balance — balance_after is set
        # after the amount is added so the record is always consistent.
        tx = Transaction(
            user_id=user_id,
            wallet_id=wallet.id,
            type="deposit",
            amount=amount,
            balance_after=wallet.balance + amount,  # estimated before commit
            reference_id=payment_intent_id,
            reference_type="stripe_payment_intent",
            status="completed",
        )
        db.add(tx)

        # Apply balance change — if this fails (e.g. constraint), tx record
        # is rolled back along with it. No orphaned credit.
        wallet.balance += amount

        # Update the estimated balance_after now that wallet.balance is updated
        tx.balance_after = wallet.balance

        try:
            await db.commit()
        except IntegrityError as exc:
            await db.rollback()
            # Unique constraint violation = already processed (race between two webhooks).
            # Re-read the transaction to confirm it was inserted by the other request.
            existing = await db.execute(
                select(Transaction).where(
                    Transaction.reference_id == payment_intent_id,
                    Transaction.type == "deposit",
                )
            )
            if existing.scalar_one_or_none():
                logger.info(f"Stripe deposit already processed (race): {payment_intent_id}")
                return success_response({"status": "already_processed"})
            # Not a dup — re-raise so Stripe retries
            raise HTTPException(status_code=500, detail="Failed to process deposit, will retry") from exc

        logger.info(f"Deposit credited: user={user_id} amount={amount} PI={payment_intent_id}")
        return success_response({"status": "credited", "transaction_id": str(tx.id)})

    elif event_type == "payment_intent.payment_failed":
        logger.warning(f"Payment failed: {data.get('id')}")
        return success_response({"status": "payment_failed"})

    logger.info(f"Unhandled Stripe event type: {event_type}")
    return success_response({"status": "unhandled_event_type"})
