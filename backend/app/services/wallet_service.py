import logging
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.exceptions import InsufficientBalanceError, NotFoundError, ValidationError
from app.models.user import User
from app.models.wallet import Transaction, Wallet

logger = logging.getLogger("polymarket")


class WalletService:

    @staticmethod
    async def withdraw(
        db: AsyncSession,
        user: User,
        amount: Decimal,
        idempotency_key: str | None = None,
    ) -> dict:
        if amount <= 0:
            raise ValidationError("Amount must be positive")

        # Idempotency: reject duplicate withdrawal if same idempotency_key used within expiry window
        if idempotency_key:
            existing = await db.execute(
                select(Transaction).where(
                    Transaction.user_id == user.id,
                    Transaction.reference_id == idempotency_key,
                    Transaction.type == "withdrawal",
                )
            )
            if existing.scalar_one_or_none():
                raise IdempotencyError("Withdrawal already processed")

        result = await db.execute(select(Wallet).where(Wallet.user_id == user.id))
        wallet = result.scalar_one_or_none()
        if not wallet:
            raise NotFoundError("Wallet not found")

        available = wallet.balance - wallet.locked_balance
        if amount > available:
            raise InsufficientBalanceError({
                "available": float(available),
                "requested": float(amount),
            })

        wallet.balance -= amount

        tx = Transaction(
            user_id=user.id,
            wallet_id=wallet.id,
            type="withdrawal",
            amount=-float(amount),
            balance_after=wallet.balance,
            reference_id=idempotency_key or "",  # store idempotency key as reference_id
            status="pending",
        )
        db.add(tx)
        await db.commit()

        logger.info(f"Withdrawal: user={user.id} amount={float(amount)}")

        return {
            "withdrawal_id": str(tx.id),
            "amount": str(amount),
            "status": "pending",
        }
