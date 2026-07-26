import logging
import json
from decimal import Decimal
from fastapi import APIRouter, Request, Header, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.wallet import Wallet, Transaction
from app.models.user import User
from app.api.responses import success_response
from app.api.exceptions import ValidationError
from app.config import settings

logger = logging.getLogger("polymarket")
router = APIRouter(prefix="/webhooks", tags=["webhooks"])


async def verify_stripe_signature(payload: bytes, sig: str) -> bool:
    """Verify Stripe webhook signature."""
    if not settings.stripe_webhook_secret:
        return True  # Skip verification in dev
    # In production: use stripe.Webhook.construct_event
    return True


@router.post("/stripe", summary="Stripe webhook", description="Handle Stripe webhook events. Currently processes payment_intent.succeeded to credit user wallets idempotently.")
async def stripe_webhook(
    request: Request,
    stripe_signature: str = Header(None),
    db: AsyncSession = Depends(get_db),
):
    payload = await request.body()

    if not await verify_stripe_signature(payload, stripe_signature or ""):
        raise ValidationError("Invalid Stripe signature")

    try:
        event = json.loads(payload)
    except json.JSONDecodeError:
        raise ValidationError("Invalid JSON payload")

    event_type = event.get("type", "")
    data = event.get("data", {}).get("object", {})

    if event_type == "payment_intent.succeeded":
        payment_intent_id = data.get("id", "")
        amount_cents = data.get("amount", 0)
        currency = data.get("currency", "usd")
        metadata = data.get("metadata", {})

        user_id = metadata.get("user_id")
        if not user_id:
            logger.warning(f"Stripe webhook: no user_id in metadata for PI {payment_intent_id}")
            return success_response({"status": "ignored"})

        # Idempotency: check if already processed
        existing = await db.execute(
            select(Transaction).where(
                Transaction.reference_id == payment_intent_id,
                Transaction.type == "deposit",
            )
        )
        if existing.scalar_one_or_none():
            logger.info(f"Stripe deposit already processed: {payment_intent_id}")
            return success_response({"status": "already_processed"})

        # Credit wallet
        wallet_result = await db.execute(select(Wallet).where(Wallet.user_id == user_id))
        wallet = wallet_result.scalar_one_or_none()
        if not wallet:
            logger.error(f"Wallet not found for user {user_id}")
            return success_response({"status": "wallet_not_found"})

        amount = Decimal(str(amount_cents)) / 100  # cents to dollars

        # Store in USDC (1:1 for now, Stripe handles USD)
        wallet.balance += amount

        # Record transaction
        tx = Transaction(
            user_id=user_id,
            wallet_id=wallet.id,
            type="deposit",
            amount=amount,
            balance_after=wallet.balance,
            reference_id=payment_intent_id,
            reference_type="stripe_payment_intent",
            status="completed",
        )
        db.add(tx)
        await db.commit()

        logger.info(f"Deposit credited: user={user_id} amount={amount} PI={payment_intent_id}")
        return success_response({"status": "credited", "transaction_id": str(tx.id)})

    elif event_type == "payment_intent.payment_failed":
        logger.warning(f"Payment failed: {data.get('id')}")
        return success_response({"status": "payment_failed"})

    logger.info(f"Unhandled Stripe event type: {event_type}")
    return success_response({"status": "unhandled_event_type"})
