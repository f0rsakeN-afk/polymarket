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
import json
import os
import secrets
import sys
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

from sqlalchemy import select

from app.database import _get_async_session_maker
from app.deps import hash_password
from app.models.market import Market, Outcome
from app.models.order import Order
from app.models.user import User
from app.models.wallet import Wallet

EMAIL = sys.argv[1] if len(sys.argv) > 1 else "e2e-private@example.com"
USERNAME = "e2eprivate"

# Where the generated credential is handed to the browser tests.
#
# GitHub's secret scanning flags this file for a hardcoded password, and it was
# right to. The value was a throwaway local account - but it was in a *public*
# repository, which is a bad habit to leave in place: every real credential that
# follows will be less scrutinised because this one looked harmless, and "looks
# harmless, it's only a test" is exactly how test credentials become the ones
# that reach production.
#
# So there is no password literal here at all. One is generated per run, used to
# write the user, and written to a gitignored file that only the browser tests
# read. It rotates on every seed, so the previously published value is dead on
# arrival.
#
# Override with E2E_PASSWORD if you need a session to survive a reseed.
CREDENTIALS_PATH = Path(__file__).resolve().parents[2] / ".e2e-credentials.json"


def _password() -> str:
    override = os.environ.get("E2E_PASSWORD")
    if override:
        return override
    return secrets.token_urlsafe(24)


async def _ensure_wallet(db, user_id) -> None:
    """Provision the wallet registration would have created.

    Idempotent, and applied on *both* paths. Seeding an existing user is the
    common case - the harness rotates a password rather than recreating anything
    - so doing this only at creation would have left every already-seeded user
    still missing one, and the wallet endpoint still 404ing for them.

    That is what happened: the E2E user was seeded before this was fixed, the
    wallet endpoint 404ed, and that was misread as a session problem for the
    better part of a day. The harness was testing a state no real user reaches,
    and every unit fixture pre-creates a wallet, so nothing else caught it.
    """
    existing = await db.execute(select(Wallet).where(Wallet.user_id == user_id))
    if existing.scalar_one_or_none() is not None:
        return
    db.add(Wallet(user_id=user_id, balance=0, locked_balance=0, currency="USDC"))
    await db.commit()
    print("provisioned missing wallet")


async def _mint_session(db, user) -> str:
    """Create the Session + RefreshToken pair a login would, and mint a token.

    Access tokens are bound to a session (`sid`), and `get_current_user` rejects
    a token whose session is missing, revoked or expired. So a seeded user
    without a session is permanently unauthorized - a state no real login
    produces, and one the browser tests had no way around except calling the
    rate-limited login endpoint themselves.
    """

    from app.deps import create_access_token
    from app.models.user import RefreshToken, Session

    expires_at = datetime.now(UTC) + timedelta(days=7)
    refresh_token = RefreshToken(
        id=uuid.uuid4(),
        user_id=user.id,
        token_hash=secrets.token_urlsafe(32),
        expires_at=expires_at,
        revoked=False,
        device_info="e2e-harness",
    )
    db.add(refresh_token)
    await db.flush()

    session = Session(
        id=uuid.uuid4(),
        user_id=user.id,
        refresh_token_id=refresh_token.id,
        expires_at=expires_at,
        revoked=False,
        user_agent="e2e-harness",
        ip_address="127.0.0.1",
    )
    db.add(session)
    await db.flush()

    token, _ = create_access_token(
        str(user.id),
        # Deliberately longer-lived than a normal access token (900s).
        #
        # The browser tests set this cookie and nothing else - no refresh cookie,
        # because the harness minted the session directly rather than through
        # `POST /auth/login`. So when a standard-lifetime token expires, there is
        # nothing to refresh with and the session is simply dead: `/auth/me`
        # returns 401, every auth-gated query disables itself, and the page sits
        # at a spinner forever with no error anywhere.
        #
        # That produced a genuinely baffling failure signature - the suite passed
        # immediately after a seed and degraded as the token aged, with failures
        # landing on a different test each run. An hour comfortably covers a
        # full suite run, including re-runs while debugging.
        expires_delta=timedelta(hours=1),
        session_id=str(session.id),
    )
    return token


async def main() -> None:
    password = _password()
    maker = _get_async_session_maker()
    async with maker() as db:
        existing = await db.execute(select(User).where(User.email == EMAIL))
        user = existing.scalar_one_or_none()
        if user:
            user.password_hash = hash_password(password)
            await db.commit()
            await _ensure_wallet(db, user.id)
            token = await _mint_session(db, user)
            await db.commit()
            print(f"exists: {EMAIL} id={user.id} (password rotated)")
            await _write_credentials(user.id, password, token)
            await seed_activity(user.id)
            return

        user = User(
            email=EMAIL,
            username=USERNAME,
            password_hash=hash_password(password),
            # The only field being set that registration would not: without it
            # login refuses, and there is no mailbox here to confirm through.
            is_email_verified=True,
        )
        db.add(user)
        await db.commit()
        await db.refresh(user)
        await _ensure_wallet(db, user.id)
        token = await _mint_session(db, user)
        await db.commit()
        print(f"created: {EMAIL} id={user.id}")
        await _write_credentials(user.id, password, token)
        await seed_activity(user.id)


async def _write_credentials(user_id, password: str, access_token: str) -> None:
    """Hand the generated credential to the browser tests, and nowhere else."""
    CREDENTIALS_PATH.write_text(
        json.dumps(
            {
                "email": EMAIL,
                "password": password,
                "user_id": str(user_id),
                # A ready-to-use access token, so the browser tests can
                # authenticate without calling /auth/login at all.
                #
                # Login is rate limited, and the limit bites exactly when a
                # developer re-runs a failing suite - which is when you most need
                # it to work. Worse, a 429 is indistinguishable from "the page
                # didn't react": the session never establishes, every
                # auth-gated query stays disabled, and the page sits at a spinner
                # forever. That reads as a broken feature and costs an hour of
                # chasing a bug that isn't there. This was the dominant cause of
                # intermittent private-feed test failures.
                "access_token": access_token,
            }
        ),
        encoding="utf-8",
    )
    try:
        CREDENTIALS_PATH.chmod(0o600)
    except OSError:
        pass
    print(f"credentials -> {CREDENTIALS_PATH}")
    # Machine-readable, so CI can capture the id instead of re-reading the JSON
    # with a relative path that is correct in exactly one working directory.
    # Getting that path wrong in a workflow produces an empty variable, which the
    # suite then reads as "not configured" and skips - a green run that measured
    # nothing, which is the failure mode this line exists to prevent.
    print(f"USER_ID={user_id}")


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