import logging
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.exceptions import (
    IdempotencyError,
    InsufficientBalanceError,
    NotFoundError,
    ValidationError,
)
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

        result = await db.execute(
            select(Wallet).where(Wallet.user_id == user.id).with_for_update()
        )
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
            amount=-amount,
            balance_after=wallet.balance,
            reference_id=idempotency_key or "",
            reference_type="withdrawal",
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

    @staticmethod
    async def confirm_withdrawal(
        db: AsyncSession,
        withdrawal_id: str,
        blockchain_tx_hash: str | None = None,
        confirmed: bool = True,
    ) -> dict:
        """
        Confirm or reject a pending withdrawal after blockchain settlement.

        - confirmed=True + blockchain_tx_hash: marks withdrawal as completed.
          The balance was already debited at submission time (pending state).
        - confirmed=False: marks as failed and reverses the balance debited at submission.
        """
        result = await db.execute(
            select(Transaction).where(
                Transaction.id == withdrawal_id,
                Transaction.type == "withdrawal",
            ).with_for_update()
        )
        tx = result.scalar_one_or_none()
        if not tx:
            raise NotFoundError("Withdrawal not found")

        if tx.status != "pending":
            raise ValidationError(f"Withdrawal is already {tx.status}")

        if confirmed:
            tx.status = "completed"
            if blockchain_tx_hash:
                tx.reference_id = blockchain_tx_hash
                tx.reference_type = "blockchain_withdrawal"
            logger.info(f"Withdrawal confirmed: id={withdrawal_id} tx={blockchain_tx_hash}")
        else:
            # Reject: reverse the balance that was debited at submission
            wallet_result = await db.execute(
                select(Wallet).where(Wallet.id == tx.wallet_id).with_for_update()
            )
            wallet = wallet_result.scalar_one_or_none()
            if wallet:
                wallet.balance -= tx.amount  # amount is negative, so this adds back
            tx.status = "failed"
            if blockchain_tx_hash:
                tx.reference_id = blockchain_tx_hash
                tx.reference_type = "blockchain_withdrawal"
            logger.warning(f"Withdrawal rejected: id={withdrawal_id} tx={blockchain_tx_hash}")

        await db.commit()
        return {"withdrawal_id": str(tx.id), "status": tx.status}
