"""Seed a signed-in-able user, so the *private* feed can be tested at all.

Every authenticated surface redirects to sign-in, which means the feed carrying
the highest-consequence frames in the product - "you were filled", "your position
changed" - is the one surface nobody has ever asked about. That is the worst
possible gap: it is the least likely to break loudly and the most costly when it
does.

Registering through the API does not help. It returns `pending_verification`
because the product correctly requires email confirmation, and this harness has no
mailbox. So the user is written directly, using the application's own model and
its own password hashing - not a bypass inserted into the auth path, which would
mean testing something the product never runs.

Run it, then log in normally:

    REDIS_PASSWORD=devpass .venv/bin/python -m harness.seed_user
"""

import asyncio
import sys

from sqlalchemy import select

from app.database import _get_async_session_maker
from app.deps import hash_password
from app.models.market import Market, Outcome
from app.models.order import Order
from app.models.user import User

EMAIL = sys.argv[1] if len(sys.argv) > 1 else "e2e-private@example.com"
USERNAME = "e2eprivate"
# Harness-only credential for a throwaway local account. Not a secret, and not
# used anywhere but a seeded dev user.
PASSWORD = "Passw0rd!x9"  # noqa: S105


async def main() -> None:
    maker = _get_async_session_maker()
    async with maker() as db:
        existing = await db.execute(select(User).where(User.email == EMAIL))
        user = existing.scalar_one_or_none()
        if user:
            print(f"exists: {EMAIL} id={user.id}")
            print(f"password: {PASSWORD}")
            await seed_activity(user.id)
            return

        user = User(
            email=EMAIL,
            username=USERNAME,
            password_hash=hash_password(PASSWORD),
            # The only field being set that registration would not: without it
            # login refuses, and there is no mailbox here to confirm through.
            is_email_verified=True,
        )
        db.add(user)
        await db.commit()
        await db.refresh(user)
        print(f"created: {EMAIL} id={user.id}")
        print(f"password: {PASSWORD}")
        await seed_activity(user.id)


async def seed_activity(user_id) -> None:
    """Give the user something for the private feed to actually change.

    Without this the "does /orders react to a fill?" test is unanswerable. A user
    with zero orders renders an empty state, and a published fill has nothing to
    replace - so the page not changing proves nothing either way. It is the
    cheapest of the three candidate explanations to eliminate, so it goes first:
    seed real rows, re-run, and whatever is left is a real fault.
    """
    maker = _get_async_session_maker()
    async with maker() as db:
        market = await db.execute(
            select(Market).where(Market.status == "active").limit(1)
        )
        market = market.scalar_one_or_none()
        if market is None:
            print("no active market to attach activity to")
            return
        outcome = await db.execute(
            select(Outcome).where(Outcome.market_id == market.id).limit(1)
        )
        outcome = outcome.scalar_one_or_none()
        if outcome is None:
            print("market has no outcomes")
            return
        db.add(Order(
            user_id=user_id,
            market_id=market.id,
            outcome_id=outcome.id,
            side="buy",
            order_type="market",
            amount=__import__("decimal").Decimal("25"),
            price=__import__("decimal").Decimal("0.61"),
            status="filled",
        ))
        await db.commit()
        print(f"seeded a filled order on {market.slug}")


if __name__ == "__main__":
    asyncio.run(main())