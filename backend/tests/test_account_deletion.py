"""Account deletion and data export.

The load-bearing question these answer is not "does the endpoint work" but
**what survives erasure**. Every table referencing a user cascades on delete, so
the tempting implementation - `DELETE FROM users` - would take the public trade
tape, the record of already-settled positions, and the transaction ledger with
it, and cascade away referral rows that are about other people's accounts.

So deletion anonymises rather than deletes, and most of what follows is about
proving that distinction rather than assuming it.
"""

import uuid
from decimal import Decimal

import pytest
import pytest_asyncio
from conftest import token_for
from httpx import AsyncClient
from sqlalchemy import select

from app.deps import verify_password
from app.models.notification import Notification
from app.models.order import Order
from app.models.position import Position
from app.models.trade import Trade
from app.models.wallet import Transaction, Wallet
from app.services.account_deletion import RETAINED_TABLES


async def _ledger_for(db_session, user, market, outcome):
    """One row in each retained table, so retention can be checked against real
    rows rather than against an assertion about a list."""
    # Wallet's PK is the inherited `id`; `user_id` is a separate unique column,
    # so `db_session.get(Wallet, user_id)` returns None for a wallet that exists.
    wallet = (
        await db_session.execute(select(Wallet).where(Wallet.user_id == user.id))
    ).scalar_one()
    rows = {
        "trade": Trade(
            user_id=user.id,
            market_id=market.id,
            outcome="Yes",
            side="buy",
            price=Decimal("0.42"),
            amount=Decimal(10),
        ),
        "order": Order(
            user_id=user.id,
            market_id=market.id,
            outcome_id=outcome.id,
            side="buy",
            order_type="limit",
            amount=Decimal(10),
            price=Decimal("0.42"),
            status="filled",
        ),
        "position": Position(user_id=user.id, market_id=market.id, outcome_id=outcome.id),
        "transaction": Transaction(
            user_id=user.id,
            wallet_id=wallet.id,
            type="deposit",
            amount=Decimal(100),
            balance_after=Decimal(1000),
        ),
    }
    db_session.add_all(rows.values())
    await db_session.commit()
    return rows


# ── Export ────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_export_requires_authentication(client: AsyncClient):
    resp = await client.get("/api/v1/account/export")
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_export_contains_every_category_not_just_the_obvious(
    client: AsyncClient, db_session, test_user, test_market
):
    """An export that omits a category invites the belief that it is complete.

    A user asking "what do you have on me?" who receives only their profile has
    been told something false - they will reasonably conclude there is nothing
    else. Completeness is the feature.
    """
    await _ledger_for(db_session, test_user, test_market, test_market.outcomes[0])
    client.cookies.set("access_token", token_for(test_user.id))

    resp = await client.get("/api/v1/account/export")

    assert resp.status_code == 200, resp.text
    body = resp.json()
    for key in (
        "account",
        "sessions",
        "orders",
        "positions",
        "trades",
        "transactions",
        "wallet",
        "comments",
        "disputes",
        "notifications",
        "alerts",
    ):
        assert key in body, f"the export omits {key!r} - it reads as complete while omitting data"

    assert body["account"]["email"] == test_user.email
    assert len(body["trades"]) == 1, "a trade exists but the export does not include it"
    assert len(body["orders"]) == 1
    assert body["wallet"]["balance"] is not None, "the wallet balance is missing from the export"


@pytest.mark.asyncio
async def test_export_is_offered_as_a_download(
    client: AsyncClient, db_session, test_user
):
    """`Content-Disposition` is what makes "save my data" work.

    Without it the export renders inline inside the SPA's own error boundary,
    which for a large account is a genuinely bad place for a multi-megabyte
    string.
    """
    client.cookies.set("access_token", token_for(test_user.id))

    resp = await client.get("/api/v1/account/export")

    assert resp.status_code == 200
    assert "attachment" in resp.headers.get("content-disposition", "")
    assert "predictx-export-" in resp.headers["content-disposition"]


@pytest.mark.asyncio
async def test_export_decimal_money_is_exact_not_rounded(
    client: AsyncClient, db_session, test_user, test_market
):
    """Money is exported as a string, because `float()` rounds it.

    A balance that comes back as 999.9999999 instead of 1000.00000000 is not a
    cosmetic problem - it is the user concluding the ledger is wrong.
    """
    await _ledger_for(db_session, test_user, test_market, test_market.outcomes[0])
    client.cookies.set("access_token", token_for(test_user.id))

    body = (await client.get("/api/v1/account/export")).json()

    balance = body["wallet"]["balance"]
    assert isinstance(balance, str), f"money must export as a string, got {type(balance)}"
    assert Decimal(balance) == Decimal(1000), f"the balance did not survive exactly: {balance}"
    assert balance == str(Decimal("1000.00000000")), (
        "the exported balance was rounded somewhere - a user comparing this against "
        "their ledger would conclude the books are wrong"
    )


# ── Step-up on deletion ───────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_deletion_requires_step_up(client: AsyncClient, db_session, test_user):
    """A bare session must not be enough to erase an account.

    "Delete my account" behind nothing but a session cookie is the single
    operation a session-riding attacker most wants, and the single one nobody
    could undo.
    """
    client.cookies.set("access_token", token_for(test_user.id))

    resp = await client.request("DELETE", "/api/v1/account", json={})

    assert resp.status_code >= 400
    await db_session.refresh(test_user)
    assert test_user.is_deleted is False, "the account was erased without step-up credentials"


@pytest.mark.asyncio
async def test_deletion_with_a_wrong_password_changes_nothing(
    client: AsyncClient, db_session, test_user
):
    from app.config import settings as app_settings

    client.cookies.set("access_token", token_for(test_user.id))
    original = test_user.email

    resp = await client.request("DELETE", "/api/v1/account", json={"password": "not-it"})

    assert resp.status_code >= 400
    assert resp.json().get("error_code") == "STEP_UP_PASSWORD_INVALID"
    await db_session.refresh(test_user)
    assert test_user.email == original, "a failed step-up still erased the account"
    assert app_settings is not None  # keep the import meaningful


@pytest_asyncio.fixture(autouse=True)
async def _clear_rate_limit_state():
    """Reset the friction counters around every test in this file.

    `record_failure` writes to shared Redis, so a test that deliberately guesses
    wrong passwords throttles the next one - which is how a correct test fails
    because of an unrelated one, and how a suite starts depending on its own
    ordering.
    """
    from app.redis import get_redis_sync

    def _wipe() -> None:
        redis = get_redis_sync()
        for key in redis.scan_iter(match="rl:*"):
            redis.delete(key)

    _wipe()
    yield
    _wipe()


@pytest.mark.asyncio
async def test_deletion_is_friction_limited(
    client: AsyncClient, db_session, test_user, monkeypatch
):
    """Deletion is a password oracle unless it is throttled.

    Two ways this goes wrong if it does. Within one IP, the guesses are free; and
    across IPs, an attacker rotating source addresses gets a fresh allowance
    every time - which is why the limit is keyed on the account rather than
    inherited from the per-IP bucket.

    Rate limiting is disabled suite-wide by `conftest`, so this asserts nothing
    unless it is switched on here - the same trap that made the admin step-up
    friction test pass with the friction removed.
    """
    from app.config import settings as app_settings

    monkeypatch.setattr(app_settings, "rate_limit_enabled", True)

    client.cookies.set("access_token", token_for(test_user.id))
    statuses = []
    for i in range(8):
        resp = await client.request("DELETE", "/api/v1/account", json={"password": f"guess-{i}"})
        statuses.append(resp.status_code)
        if resp.status_code == 429:
            break

    assert 429 in statuses, f"deletion never throttled: {statuses}"


@pytest.mark.asyncio
async def test_a_2fa_account_cannot_delete_with_a_password_alone(
    client: AsyncClient, db_session, test_user
):
    """The server decides the required factor, not the client."""
    test_user.is_2fa_enabled = True
    test_user.totp_secret_encrypted = "irrelevant-for-this-assertion"
    await db_session.commit()
    client.cookies.set("access_token", token_for(test_user.id))

    resp = await client.request("DELETE", "/api/v1/account", json={"password": "User!Pass1"})

    assert resp.status_code >= 400
    assert resp.json().get("error_code") == "STEP_UP_2FA_REQUIRED"


# ── What erasure removes ──────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_erasure_removes_the_person(
    client: AsyncClient, db_session, test_user, test_market
):
    from app.models.alert import Alert

    db_session.add(Notification(user_id=test_user.id, title="t", body="b", type="info"))
    db_session.add(Alert(
        user_id=test_user.id,
        market_id=test_market.id,
        outcome="Yes",
        condition="above",
        trigger_price=Decimal("0.5"),
    ))
    await db_session.commit()
    original_email = test_user.email

    client.cookies.set("access_token", token_for(test_user.id))
    resp = await client.request("DELETE", "/api/v1/account", json={"password": "User!Pass1"})

    assert resp.status_code == 200, resp.text
    await db_session.refresh(test_user)

    assert test_user.email != original_email
    assert original_email not in test_user.email, (
        "the tombstone address is derived from the old one, so anyone reading the "
        "users table can reverse it"
    )
    assert test_user.username != test_user.email
    assert test_user.is_deleted is True
    assert test_user.deleted_at is not None
    assert test_user.is_active is False
    assert test_user.is_admin is False
    assert test_user.totp_secret_encrypted is None
    assert test_user.referral_code is None

    remaining = (
        await db_session.execute(
            Notification.__table__.select().where(Notification.user_id == test_user.id)
        )
    ).fetchall()
    assert not remaining, "notifications are private data and should have been erased"


@pytest.mark.asyncio
async def test_the_tombstone_password_verifies_against_nothing(
    client: AsyncClient, db_session, test_user
):
    """The erasure hash must be a *real* bcrypt hash, not an obvious sentinel.

    Two things break if it is not. `bcrypt.checkpw` raises on an unparseable
    salt, so a tombstone of "!" would turn a login attempt into a 500. And
    verification returns instantly rather than in ~100 ms, so anyone who knows an
    address could time a login and learn "this account existed and was deleted" -
    an enumeration oracle about precisely the people who left.
    """
    client.cookies.set("access_token", token_for(test_user.id))
    resp = await client.request("DELETE", "/api/v1/account", json={"password": "User!Pass1"})
    assert resp.status_code == 200, resp.text

    await db_session.refresh(test_user)
    stored = test_user.password_hash

    assert stored.startswith("$2"), f"the tombstone is not a real bcrypt hash: {stored!r}"
    for candidate in ("", "password", "User!Pass1", stored):
        assert verify_password(candidate, stored) is False


@pytest.mark.asyncio
async def test_an_existing_session_stops_working_immediately(
    client: AsyncClient, db_session, test_user
):
    """Erasure takes effect on the next request, not at the next login.

    This is the difference between a revocation that means something and one that
    is decorative. If it only blocked future logins, a stolen cookie for a deleted
    account would keep working until its token expired - which for a user who
    deleted precisely because they were worried is the whole ballgame.
    """
    token = token_for(test_user.id)
    client.cookies.set("access_token", token)

    # Live before deletion.
    assert (await client.get("/api/v1/account/deletion-impact")).status_code == 200

    resp = await client.request("DELETE", "/api/v1/account", json={"password": "User!Pass1"})
    assert resp.status_code == 200, resp.text

    # Dead immediately, with the very same cookie.
    after = await client.get("/api/v1/account/deletion-impact")
    assert after.status_code >= 400, (
        "the account was erased but its session still authenticates - the "
        "revocation is decorative"
    )


@pytest_asyncio.fixture
async def addressable_user(db_session):
    """A user whose email the validator accepts.

    `test_user` is on `example.com`, which `EmailStr` rejects outright as a
    reserved special-use domain - so any test that posts the address through
    `/auth/login` or `/auth/register` gets a 422 about the email before the
    endpoint under test is ever reached. Registering here keeps the address real
    enough to travel the whole auth path.
    """
    from conftest import create_login_session

    from app.deps import hash_password
    from app.models.user import User
    from app.models.wallet import Wallet

    uid = uuid.uuid4().hex[:8]
    user = User(
        email=f"member_{uid}@predictx.test-domain.com",
        username=f"member_{uid}",
        password_hash=hash_password("User!Pass1"),
        is_email_verified=True,
        is_active=True,
    )
    db_session.add(user)
    await db_session.flush()
    db_session.add(Wallet(user_id=user.id, balance="1000.00", locked_balance="0", currency="USDC"))
    await create_login_session(db_session, user)
    await db_session.commit()
    await db_session.refresh(user)
    return user


@pytest.mark.asyncio
async def test_a_deleted_account_cannot_sign_in_again(
    client: AsyncClient, db_session, addressable_user
):
    """Erasure must not leave the account reachable by its old credentials."""
    client.cookies.set("access_token", token_for(addressable_user.id))
    original_email = addressable_user.email
    assert (
        await client.request(
            "DELETE", "/api/v1/account", json={"password": "User!Pass1"}
        )
    ).status_code == 200

    client.cookies.clear()
    resp = await client.post(
        "/api/v1/auth/login", json={"email": original_email, "password": "User!Pass1"}
    )

    assert resp.status_code == 401, (
        f"a deleted account can still sign in: {resp.status_code} {resp.text}"
    )


@pytest.mark.asyncio
async def test_the_address_is_released_so_the_user_can_return(
    client: AsyncClient, db_session, addressable_user
):
    """Deleting and later signing up again is the actual journey.

    If erasure left the address claimed, the user who deletes their account has
    permanently burned the email they would use to come back - and would have no
    way to say so.
    """
    client.cookies.set("access_token", token_for(addressable_user.id))
    original_email = addressable_user.email
    assert (
        await client.request(
            "DELETE", "/api/v1/account", json={"password": "User!Pass1"}
        )
    ).status_code == 200

    client.cookies.clear()
    resp = await client.post(
        "/api/v1/auth/register",
        json={
            "email": original_email,
            "username": f"returning_{uuid.uuid4().hex[:8]}",
            "password": "Return!Pass1",
        },
    )

    assert resp.status_code in (200, 201), (
        f"the address was not released - a user cannot return after deleting: {resp.text}"
    )


# ── What erasure keeps ────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_erasure_keeps_the_ledger(
    client: AsyncClient, db_session, test_user, test_market
):
    """The core assertion. A `DELETE FROM users` would fail this.

    Trades, orders, positions and transactions are the market's shared history and
    its accounting obligation. They survive erasure, no longer attached to a
    person. Losing them would take the user's trades off the public tape and erase
    the record of positions they had already settled - and would destroy the very
    ledger the admin audit trail exists to reference.
    """
    rows = await _ledger_for(db_session, test_user, test_market, test_market.outcomes[0])
    ids = {name: row.id for name, row in rows.items()}

    client.cookies.set("access_token", token_for(test_user.id))
    resp = await client.request("DELETE", "/api/v1/account", json={"password": "User!Pass1"})
    assert resp.status_code == 200, resp.text
    await db_session.refresh(test_user)

    for model, name in (
        (Trade, "trade"),
        (Order, "order"),
        (Position, "position"),
        (Transaction, "transaction"),
    ):
        surviving = await db_session.get(model, ids[name])
        assert surviving is not None, (
            f"the {name} was deleted along with the user - the ledger is the market's "
            "history and must survive erasure"
        )
        assert surviving.user_id == test_user.id, (
            f"the {name} no longer resolves to the tombstone row, so the ledger has a hole"
        )


@pytest.mark.asyncio
async def test_retained_tables_are_named_not_implied(
    client: AsyncClient, db_session, test_user
):
    """"We deleted the user" and "we deleted their data" are different claims.

    Only one of them is true here, so the response says which - listing the
    retained tables rather than leaving the user to discover the difference by
    noticing their trade history is still visible.
    """
    client.cookies.set("access_token", token_for(test_user.id))

    body = (await client.request("DELETE", "/api/v1/account", json={"password": "User!Pass1"})).json()

    retained = body["data"]["retained"]["tables"]
    assert set(retained) == set(RETAINED_TABLES)
    assert "trades" in retained and "transactions" in retained
    assert body["data"]["retained"]["reason"], "retention is unexplained"


# ── Refusal is the honest answer when money is outstanding ────────────────────


@pytest.mark.asyncio
async def test_deletion_is_refused_while_orders_are_open(
    client: AsyncClient, db_session, test_user, test_market
):
    """An open order has locked funds. It cannot be walked away from.

    Proceeding would leave the funds reserved against a market position owned by
    nobody, and the user who placed the order never consented to that.
    """
    db_session.add(
        Order(
            user_id=test_user.id,
            market_id=test_market.id,
            outcome_id=test_market.outcomes[0].id,
            side="buy",
            order_type="limit",
            amount=Decimal(10),
            price=Decimal("0.42"),
            status="pending",
        )
    )
    await db_session.commit()
    client.cookies.set("access_token", token_for(test_user.id))

    resp = await client.request("DELETE", "/api/v1/account", json={"password": "User!Pass1"})

    assert resp.status_code == 409, resp.text
    await db_session.refresh(test_user)
    assert test_user.is_deleted is False, "the account was deleted with funds still locked"


@pytest.mark.asyncio
async def test_deletion_is_refused_while_a_position_is_unsettled(
    client: AsyncClient, db_session, test_user, test_market
):
    """A position in a market that has not resolved is money owed to the user.

    Erasing the account would strand it: the payout lands on a wallet belonging
    to nobody, and the market loses a holder mid-life.
    """
    position = Position(
        user_id=test_user.id,
        market_id=test_market.id,
        outcome_id=test_market.outcomes[0].id,
        shares_held=Decimal(5),
    )
    db_session.add(position)
    await db_session.commit()
    client.cookies.set("access_token", token_for(test_user.id))

    resp = await client.request("DELETE", "/api/v1/account", json={"password": "User!Pass1"})

    assert resp.status_code == 409, resp.text
    detail = resp.json()["details"]
    assert detail["unsettled_positions"] == 1
    assert "resolve" in detail["message"].lower(), "the user is told what to do about it"


@pytest.mark.asyncio
async def test_deletion_succeeds_once_the_position_has_settled(
    client: AsyncClient, db_session, test_user, test_market
):
    """The refusal is temporary by design - it must actually lift.

    A block that never clears is worse than no feature at all: the user has been
    told the account can be deleted and then finds it cannot, forever.
    """
    position = Position(
        user_id=test_user.id,
        market_id=test_market.id,
        outcome_id=test_market.outcomes[0].id,
        shares_held=Decimal(5),
    )
    db_session.add(position)
    test_market.status = "resolved"
    await db_session.commit()

    client.cookies.set("access_token", token_for(test_user.id))
    resp = await client.request("DELETE", "/api/v1/account", json={"password": "User!Pass1"})

    assert resp.status_code == 200, resp.text
    assert await db_session.get(Position, position.id) is not None


@pytest.mark.asyncio
async def test_deletion_impact_previews_the_block_before_the_user_commits(
    client: AsyncClient, db_session, test_user, test_market
):
    """A condition discovered *after* the irreversible step is a design failure.

    The flow ends in an erasure. Introducing a new blocking condition at the last
    step is the worst possible place to do it, so the check is a read the UI can
    ask for first.
    """
    db_session.add(
        Order(
            user_id=test_user.id,
            market_id=test_market.id,
            outcome_id=test_market.outcomes[0].id,
            side="buy",
            order_type="limit",
            amount=Decimal(10),
            price=Decimal("0.42"),
            status="pending",
        )
    )
    await db_session.commit()
    client.cookies.set("access_token", token_for(test_user.id))

    body = (await client.get("/api/v1/account/deletion-impact")).json()

    assert body["data"]["can_delete"] is False
    assert body["data"]["open_orders"] == 1
    assert body["data"]["blocked_detail"]["message"]

