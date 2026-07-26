import logging
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.wallet import Wallet, Transaction
from app.models.user import User
from app.api.exceptions import NotFoundError, ValidationError, InsufficientBalanceError

logger = logging.getLogger("polymarket")


class WalletService:

    @staticmethod
    async def withdraw(
        db: AsyncSession,
        user: User,
        amount: Decimal,
    ) -> dict:
        if amount <= 0:
            raise ValidationError("Amount must be positive")

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
            status="pending",
        )
        db.add(tx)
        await db.commit()

        logger.info(f"Withdrawal: user={user.id} amount={float(amount)}")

        return {
            "withdrawal_id": str(tx.id),
            "amount": float(amount),
            "status": "pending",
        }
