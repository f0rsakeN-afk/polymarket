"""A referral record must survive either party leaving.

Nothing hard-deletes a user today - erasure anonymises, which is what
`test_account_deletion.py` covers. This file deliberately performs the hard
delete anyway, because that is the case the schema has to survive:

"Right to be forgotten" is a reasonable thing for a future engineer, or a
regulator, to assume already works. The day someone adds `DELETE FROM users` to
satisfy that, the cascading foreign keys decide what a rewards ledger looks like
afterwards - silently, and without anyone reviewing it.

The asymmetry is the point, and it runs opposite to the intuitive one:

* Delete the **referred** user and the referrer's *already-paid* earnings must
  survive. `reward_amount` is money that left a wallet, so the record of it has to
  outlive both people.
* Delete the **referrer** and a still-`pending` row - a reward someone is owed -
  must survive. That is not a privacy question: cascading the referrer away
  confiscates money from a user who did nothing wrong.

## A note on reading rows back

Each test captures the referral id and then re-reads with an explicit
`populate_existing` select. That detail is the whole test: a plain select - or
`AsyncSession.get` - answers from the identity map, which still holds the row
this test just inserted, so it reports the pre-delete state and the assertion
passes for entirely the wrong reason. Touching an attribute after `expire_all()`
fails differently again, raising `MissingGreenlet` from a lazy load outside the
async greenlet.
"""

from decimal import Decimal

import pytest
from conftest import create_login_session, token_for
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete, func, select
from sqlalchemy.exc import IntegrityError

from app.models.referral import Referral
from app.models.user import User
from app.models.wallet import Wallet


async def _user_with_wallet(db_session, label: str) -> User:
    uid = f"{label}-{id(db_session) % 100000}"
    user = User(
        email=f"{uid}@referral-guard.test",
        username=uid,
        password_hash="not-a-real-hash",
        is_email_verified=True,
        is_active=True,
        referral_code=f"CODE-{label.upper()}",
    )
    db_session.add(user)
    await db_session.flush()
    db_session.add(Wallet(user_id=user.id, balance="0", locked_balance="0", currency="USDC"))
    # Auth validates a `sid` claim, so a token minted without a session is
    # rejected - and that rejection reads as "not signed in", not "no session".
    await create_login_session(db_session, user)
    await db_session.commit()
    await db_session.refresh(user)
    return user


async def _referral(db_session, referrer, referred, **over) -> Referral:
    """`referred=None` builds the legitimate one-sided orphan."""
    referral = Referral(
        referrer_id=referrer.id if referrer else None,
        referred_id=referred.id if referred else None,
        referral_code=(referrer.referral_code if referrer else None) or "CODE",
        **{**over, "status": over.get("status", "pending")},
    )
    db_session.add(referral)
    await db_session.commit()
    await db_session.refresh(referral)
    return referral


async def _reread(db_session, referral_id: str) -> Referral | None:
    """Read a row the database has actually acted on, never the identity map.

    `populate_existing` is the load-bearing part. A plain `select` returns the
    instance already in the identity map *without* refreshing it, so it reports
    the pre-delete state - which is how a test asserting that SET NULL worked
    ends up proving nothing at all.
    """
    result = await db_session.execute(
        select(Referral).where(Referral.id == referral_id).execution_options(
            populate_existing=True
        )
    )
    return result.scalars().first()


# ── The referred user leaves ──────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_paid_earnings_outlive_the_person_they_were_earned_from(db_session):
    """The referrer's completed reward must not vanish with the referred user.

    This is money that already left a wallet. Losing the row would also lose the
    `reference_id` on the payout transaction, leaving an accounting entry pointing
    at nothing.
    """
    referrer = await _user_with_wallet(db_session, "earner")
    referred = await _user_with_wallet(db_session, "departed")
    referral = await _referral(
        db_session, referrer, referred, status="completed", reward_amount=Decimal("5.00")
    )
    referral_id = referral.id

    await db_session.execute(delete(User).where(User.id == referred.id))
    await db_session.commit()

    surviving = await _reread(db_session, referral_id)
    assert surviving is not None, (
        "the referral was destroyed along with the referred user - the referrer's "
        "already-paid earnings disappeared with it"
    )
    assert surviving.referred_id is None
    assert surviving.referrer_id == referrer.id
    assert surviving.reward_amount == Decimal("5.00"), "the amount earned was altered"


@pytest.mark.asyncio
async def test_a_referrers_totals_are_unmoved_when_a_referred_user_leaves(db_session):
    """Not just the row - the aggregate the referrer actually sees.

    A surviving row with a corrupted amount would pass the test above and still
    show the wrong number in the product.
    """
    referrer = await _user_with_wallet(db_session, "agg")
    referred = await _user_with_wallet(db_session, "leaver")
    await _referral(db_session, referrer, referred, status="completed", reward_amount=Decimal("7.50"))

    await db_session.execute(delete(User).where(User.id == referred.id))
    await db_session.commit()

    total = await db_session.scalar(
        select(func.sum(Referral.reward_amount)).where(Referral.referrer_id == referrer.id)
    )
    assert total == Decimal("7.50"), (
        f"the referrer's earnings became {total} because someone they referred "
        "left the platform"
    )


# ── The referrer leaves ───────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_a_pending_reward_is_not_confiscated_when_the_referrer_leaves(db_session):
    """The case that argues against CASCADE on either column.

    A `pending` row is an entitlement. If the referrer leaves, the referred user
    is still here and is still owed it.
    """
    referrer = await _user_with_wallet(db_session, "referrer")
    referred = await _user_with_wallet(db_session, "entitled")
    referral = await _referral(db_session, referrer, referred, status="pending")
    referral_id = referral.id

    await db_session.execute(delete(User).where(User.id == referrer.id))
    await db_session.commit()

    surviving = await _reread(db_session, referral_id)
    assert surviving is not None, (
        "a pending referral reward was destroyed along with the referrer - money "
        "owed to a user who is still here was silently confiscated"
    )
    assert surviving.referrer_id is None
    assert surviving.referred_id == referred.id
    assert surviving.status == "pending"


# ── An orphaned row is still a record ─────────────────────────────────────────


@pytest.mark.asyncio
async def test_the_orphaned_referral_is_served_without_pretending_to_have_an_id(db_session):
    """`str(None)` would ship the literal string "None" as an id.

    It looks like a uuid to a client, survives a round trip, and fails later at a
    place with no connection to the cause.
    """
    from app.app import app

    referrer = await _user_with_wallet(db_session, "api")
    referred = await _user_with_wallet(db_session, "apigone")
    await _referral(db_session, referrer, referred, status="completed")

    await db_session.execute(delete(User).where(User.id == referred.id))
    await db_session.commit()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        c.cookies.set("access_token", token_for(referrer.id))
        resp = await c.get("/api/v1/referrals/stats")

    assert resp.status_code == 200, resp.text
    referrals = resp.json()["data"]["referrals"]
    assert len(referrals) == 1, "the referrer lost the row describing their own referral"
    assert referrals[0]["referred_id"] is None, (
        f"expected null, got {referrals[0]['referred_id']!r} - an orphaned referral "
        "must not invent an id"
    )


# ── The integrity constraint ──────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_a_referral_naming_neither_party_is_refused(db_session):
    """One side null is a legitimate orphan. Neither is not a record of anything.

    Without the constraint a future INSERT could fabricate a referral that no
    aggregate would ever explain.
    """
    db_session.add(
        Referral(referrer_id=None, referred_id=None, referral_code="GHOST", status="pending")
    )
    with pytest.raises(IntegrityError):
        await db_session.commit()
    await db_session.rollback()


@pytest.mark.asyncio
async def test_a_referral_naming_one_party_is_allowed(db_session):
    """The other half of the constraint - it must not be so strict that it blocks
    the legitimate orphaned state it exists to permit."""
    referrer = await _user_with_wallet(db_session, "onesided")
    await _referral(db_session, referrer, None, status="pending")

    total = await db_session.scalar(select(func.count()).select_from(Referral))
    assert total == 1, "the one-sided orphan should have been accepted"