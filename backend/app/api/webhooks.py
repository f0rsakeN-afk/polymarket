import logging
from decimal import Decimal

import stripe
from fastapi import APIRouter, Depends, Header, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.exceptions import UnauthorizedError, ValidationError
from app.api.responses import success_response
from app.config import settings
from app.database import get_db
from app.models.wallet import Transaction, Wallet

logger = logging.getLogger("PredictX")
router = APIRouter(prefix="/webhooks", tags=["webhooks"])

STRIPE_TOLERANCE = 300  # 5 minutes


async def verify_stripe_signature(payload: bytes, sig_header: str, secret: str) -> dict:
    """Verify a Stripe delivery and parse it into an event dict.

    Contract:
      * returns the parsed event as a **plain dict** (stripe's typed objects
        are not mappings • ``event.get(...)`` would raise • so we flatten at
        this boundary and the rest of the handler works with plain JSON);
      * raises :class:`UnauthorizedError` (401) when the delivery cannot be
        authenticated • signature missing/malformed/mismatched, timestamp
        outside the tolerance window, or no secret configured (fail closed:
        an unverifiable delivery must never be trusted);
      * raises :class:`ValidationError` (422) only once the signature has been
        verified, when the authenticated body isn't a usable Stripe event.

    ``stripe.Webhook.construct_event`` verifies the signature *before* it
    parses JSON, so a parse failure can only happen for an authentically
    signed body • that ordering is what lets us distinguish 401 from 422.
    """
    if not secret:
        # Misconfiguration must not become "accept everything".
        logger.error("STRIPE_WEBHOOK_SECRET is not configured • rejecting webhook")
        raise UnauthorizedError("Webhook signing secret is not configured")

    try:
        body = payload.decode("utf-8")
    except UnicodeDecodeError:
        # Cannot even feed it to the verifier • treat as unauthenticated.
        raise UnauthorizedError("Invalid Stripe signature")

    try:
        event = stripe.Webhook.construct_event(
            body, sig_header, secret, tolerance=STRIPE_TOLERANCE
        )
        return event.to_dict()  # nested StripeObjects → plain dicts
    except stripe.SignatureVerificationError as e:
        logger.warning(f"Stripe signature verification failed: {e}")
        raise UnauthorizedError("Invalid Stripe signature")
    except (ValueError, TypeError, KeyError, AttributeError) as e:
        # Signature was verified above (verification runs before parsing), so
        # anything else here means: authentic but not a usable Stripe event →
        # 422, not 401. Shape errors surface as ValueError (bad JSON) or as
        # KeyError/AttributeError from Event construction (e.g. a signed body
        # that isn't an event object at all).
        logger.error(f"Stripe webhook payload could not be parsed: {e}")
        raise ValidationError(
            "Webhook body is not a valid Stripe event",
            error_code="INVALID_WEBHOOK_PAYLOAD",
        )


@router.post("/stripe", summary="Stripe webhook", description="Handle Stripe webhook events. Currently processes payment_intent.succeeded to credit user wallets idempotently.")
async def stripe_webhook(
    request: Request,
    stripe_signature: str = Header(None),
    db: AsyncSession = Depends(get_db),
):
    payload = await request.body()

    # Raises UnauthorizedError (401) / ValidationError (422) • handled globally.
    event = await verify_stripe_signature(
        payload, stripe_signature or "", settings.stripe_webhook_secret
    )

    # stripe.Event is a dict-like object
    event_type = event.get("type", "")
    data = event.get("data", {}).get("object", {})

    if event_type == "payment_intent.succeeded":
        payment_intent_id = data.get("id", "")
        amount_cents = data.get("amount", 0)
        currency = data.get("currency", "usd")
        if currency.lower() != "usd":
            logger.warning(f"Stripe webhook: unexpected currency {currency} for PI {payment_intent_id}")
            return success_response({"status": "ignored_currency"})
        metadata = data.get("metadata", {})

        user_id = metadata.get("user_id")
        if not user_id:
            logger.warning(f"Stripe webhook: no user_id in metadata for PI {payment_intent_id}")
            return success_response({"status": "ignored"})

        # Idempotency: deposits carry a partial unique index on reference_id, so a
        # redelivered payment intent can never double-credit. Check before taking
        # the wallet lock so redeliveries don't even try to insert.
        already = await db.execute(
            select(Transaction).where(
                Transaction.reference_id == payment_intent_id,
                Transaction.type == "deposit",
            )
        )
        if already.scalar_one_or_none():
            logger.info(f"Stripe deposit already processed: {payment_intent_id}")
            return success_response({"status": "already_processed"})

        # Credit wallet • lock row to prevent concurrent webhook double-credit
        wallet_result = await db.execute(
            select(Wallet).where(Wallet.user_id == user_id).with_for_update()
        )
        wallet = wallet_result.scalar_one_or_none()
        if not wallet:
            # Return 500 so Stripe retries • the wallet should exist for any active user
            logger.error(f"Wallet not found for user {user_id}")
            raise HTTPException(status_code=500, detail="Wallet not found, will retry")

        amount = (Decimal(amount_cents) / Decimal(100)).quantize(Decimal("0.01"))  # cents to dollars, Decimal-safe

        # Build transaction record BEFORE updating balance • balance_after is set
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

        # Apply balance change • if this fails (e.g. constraint), tx record
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
            # Not a dup • re-raise so Stripe retries
            raise HTTPException(status_code=500, detail="Failed to process deposit, will retry") from exc

        logger.info(f"Deposit credited: user={user_id} amount={amount} PI={payment_intent_id}")
        return success_response({"status": "credited", "transaction_id": str(tx.id)})

    elif event_type == "payment_intent.payment_failed":
        logger.warning(f"Payment failed: {data.get('id')}")
        return success_response({"status": "payment_failed"})

    logger.info(f"Unhandled Stripe event type: {event_type}")
    return success_response({"status": "unhandled_event_type"})
