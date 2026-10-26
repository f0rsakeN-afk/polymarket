"""Account deletion and data export.

## Why deletion does not delete the row

Every table referencing a user cascades: trades, positions, orders, the
transaction ledger, comments, disputes, liquidity positions, and referrals. A
plain `DELETE FROM users` would therefore:

* take the user's trades off the **public trade tape** - the market history
  everyone else reads;
* erase the record of positions they had **already settled**, including what they
  won;
* destroy the **financial ledger**, which is the thing the admin audit trail
  exists to reference. A treasury distribution moves transactions; deleting the
  user would leave an audit row pointing at nothing;
* cascade away **referral rows that are about other people** - a referral is a
  relationship, and losing it because one side left is a record of someone else's
  account disappearing.

So erasure **anonymises**. The row survives as a tombstone with every personal
attribute replaced; the trading and financial records survive, no longer attached
to a person. The same reasoning that put `actor_id SET NULL` on the admin audit
table, applied to the whole account.

## What is erased and what is kept, stated explicitly

The lists are in the code rather than implied by which tables happen to cascade,
because "we deleted the user" and "we deleted their data" are different claims
and only one of them is true.

**Erased** - private data with no value to anyone but the user: sessions and
refresh tokens, notifications and their preferences, alerts, email, username,
password hash, 2FA secret, referral code.

**Kept** - the financial and public record: trades, orders, positions,
transactions, wallet ledger, disputes, comments, liquidity positions, referral
rows. These are either the market's shared history or an accounting obligation.

## Refusal is the honest answer when money is outstanding

A user with an open order has locked funds. A user holding a position in a market
that has not resolved is owed money. Neither can be walked away from, and
pretending otherwise would strand the counterparty. So deletion is **refused**
with a message naming what is in the way, rather than proceeding and leaving a
market with a position owned by nobody.
"""

import logging
import secrets
import uuid
from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.deps import hash_password
from app.models.alert import Alert
from app.models.market import STATUS_REJECTED, STATUS_RESOLVED, Market
from app.models.notification import Notification, NotificationPreference
from app.models.order import Order
from app.models.position import Position
from app.models.user import RefreshToken, Session, User

logger = logging.getLogger("PredictX")

# Order statuses that no longer reserve funds - the exhaustive persisted set is
# pending, partial, filled, cancelled, expired, so everything else is live.
# (`"duplicate"` appears in `OrderResult` but is never written to a row, so it is
# deliberately absent here.)
TERMINAL_ORDER_STATUSES = ("filled", "cancelled", "expired")

# Market statuses past which positions are settled and owe nothing further.
# `closed`, `resolving` and `dispute_window` are *not* here: they are all on the
# way to resolution, so a position in one is still owed money.
SETTLED_MARKET_STATUSES = (STATUS_RESOLVED, STATUS_REJECTED)

# Tables whose rows are deliberately left in place. Named here so the intent is
# a decision someone can read rather than an accident of the schema.
RETAINED_TABLES = (
    "trades",
    "orders",
    "positions",
    "transactions",
    "wallets",
    "disputes",
    "comments",
    "liquidity_positions",
    "referrals",
)


class AccountDeletionBlockedError(Exception):
    """Deletion refused because the account still holds or owes money.

    Carries the specifics rather than a generic message, because "cannot delete"
    with no detail leaves the user with nothing to act on.
    """

    def __init__(self, open_orders: int, unsettled_positions: int):
        self.open_orders = open_orders
        self.unsettled_positions = unsettled_positions
        super().__init__(
            f"{open_orders} open order(s) and {unsettled_positions} position(s) in "
            "markets that have not resolved"
        )

    def detail(self) -> dict:
        return {
            "open_orders": self.open_orders,
            "unsettled_positions": self.unsettled_positions,
            "message": (
                "Close or cancel your open orders, and wait for your positions' "
                "markets to resolve, before deleting your account. Those hold "
                "funds that cannot simply be discarded."
            ),
        }


async def outstanding_obligations(db: AsyncSession, user_id) -> tuple[int, int]:
    """(open orders, positions in unsettled markets)."""
    open_orders = await db.scalar(
        select(func.count())
        .select_from(Order)
        .where(Order.user_id == user_id, Order.status.notin_(TERMINAL_ORDER_STATUSES))
    )

    unsettled = await db.scalar(
        select(func.count())
        .select_from(Position)
        .join(Market, Position.market_id == Market.id)
        .where(
            Position.user_id == user_id,
            Position.shares_held != 0,
            Market.status.notin_(SETTLED_MARKET_STATUSES),
        )
    )
    return int(open_orders or 0), int(unsettled or 0)


async def anonymise_account(db: AsyncSession, user: User) -> dict:
    """Erase the identity, keep the ledger. Returns a summary of what was done.

    Deliberately does not touch `User.id`, so trades, positions and transactions
    keep resolving to *something* and the market's history stays coherent.
    """
    now = datetime.now(UTC)

    open_orders, unsettled = await outstanding_obligations(db, user.id)
    if open_orders or unsettled:
        raise AccountDeletionBlockedError(open_orders, unsettled)

    # ── Erased: sessions and credentials ─────────────────────────────────────
    # Revoked before deleted, so a failure part-way through still locks the
    # account out rather than leaving live sessions behind.
    await db.execute(
        update(Session).where(Session.user_id == user.id).values(revoked=True)
    )
    await db.execute(
        update(RefreshToken).where(RefreshToken.user_id == user.id).values(revoked=True)
    )

    # ── Erased: private data ─────────────────────────────────────────────────
    notifications = await db.scalar(
        select(func.count()).select_from(Notification).where(Notification.user_id == user.id)
    )
    await db.execute(delete(Notification).where(Notification.user_id == user.id))
    await db.execute(
        delete(NotificationPreference).where(NotificationPreference.user_id == user.id)
    )
    alerts = await db.scalar(select(func.count()).select_from(Alert).where(Alert.user_id == user.id))
    await db.execute(delete(Alert).where(Alert.user_id == user.id))

    # ── Anonymised: identity ─────────────────────────────────────────────────
    # The tombstone address is random rather than derived from the old email, so
    # it cannot be reversed or correlated by anyone reading the users table - and
    # it carries no timestamp or id, because either would turn a row that claims
    # to hold nothing into one holding metadata about the person who used to be
    # here.
    tombstone = f"deleted-{uuid.uuid4().hex[:32]}@deleted.invalid"
    user.email = tombstone
    user.username = f"deleted_{uuid.uuid4().hex[:16]}"
    # Unusable rather than removed: the column is NOT NULL, and a value that
    # cannot verify against anything is stronger than a null that might one day
    # be bypassed by a code path that forgot to check.
    #
    # It is a *real* bcrypt hash, not an obviously-invalid sentinel, and that
    # distinction is the whole point. Login spends ~100 ms verifying a hash; a
    # tombstone that fails to parse returns instantly, so anyone who knows an
    # address could measure a login and learn "this account existed and was
    # deleted" - an enumeration oracle about the people who left. Hashing a
    # discarded random secret keeps the timing identical to a live account, and
    # the secret is never stored, so nothing verifies against it.
    user.password_hash = hash_password(secrets.token_urlsafe(32))
    user.totp_secret_encrypted = None
    user.is_2fa_enabled = False
    user.is_2fa_pending = False
    user.referral_code = None
    user.is_email_verified = False
    user.is_active = False
    # Belt and braces: an erased account has no business remaining an admin,
    # and a row with no credentials should not be able to escalate.
    user.is_admin = False
    user.is_deleted = True
    user.deleted_at = now

    await db.commit()

    logger.info(
        f"Account anonymised: id={user.id} sessions_revoked "
        f"notifications_erased={notifications} alerts_erased={alerts} "
        f"ledger_retained={','.join(RETAINED_TABLES)}"
    )

    return {
        "erased": {
            "sessions": "revoked and removed",
            "notifications": notifications,
            "alerts": alerts,
            "email": True,
            "username": True,
            "password_hash": True,
            "two_factor": True,
            "referral_code": True,
        },
        "retained": {
            "tables": list(RETAINED_TABLES),
            "reason": (
                "Financial and public records are kept so the market history and "
                "the ledger stay coherent. They are no longer attached to a person."
            ),
        },
    }


async def export_account(db: AsyncSession, user: User) -> dict:
    """Everything held about this account, in one machine-readable document.

    Modelled on what a user would assemble by hand if they asked "what do you have
    on me?" - and deliberately complete rather than minimal. An export that
    silently omits the positions row is worse than none, because it invites the
    belief that it is the whole picture.
    """
    from app.models.comment import Comment
    from app.models.dispute import Dispute
    from app.models.trade import Trade
    from app.models.wallet import Transaction, Wallet

    async def rows(model) -> list[dict]:
        found = (
            await db.execute(select(model).where(model.user_id == user.id))
        ).scalars().all()
        return [_serialisable(row) for row in found]

    wallet = (
        await db.execute(select(Wallet).where(Wallet.user_id == user.id))
    ).scalar_one_or_none()

    return {
        "exported_at": datetime.now(UTC).isoformat(),
        "account": {
            "id": str(user.id),
            "email": user.email,
            "username": user.username,
            "is_admin": user.is_admin,
            "is_active": user.is_active,
            "is_email_verified": user.is_email_verified,
            "created_at": user.created_at.isoformat() if user.created_at else None,
            "is_deleted": user.is_deleted,
        },
        # Sessions, not refresh tokens. What a user needs in order to spot a
        # stranger in their account list is which devices and addresses have been
        # used - not the token hashes, which are credential material and would
        # turn "export my data" into a way to obtain live refresh tokens.
        "sessions": await rows(Session),
        "orders": await rows(Order),
        "positions": await rows(Position),
        "trades": await rows(Trade),
        "transactions": await rows(Transaction),
        "wallet": {
            "balance": str(wallet.balance) if wallet else None,
            "locked_balance": str(wallet.locked_balance) if wallet else None,
            "currency": wallet.currency if wallet else None,
        },
        "comments": await rows(Comment),
        "disputes": await rows(Dispute),
        "notifications": await rows(Notification),
        "alerts": await rows(Alert),
    }


def _serialisable(row) -> dict:
    """Row → plain data, with the two types that JSON cannot hold handled."""
    out = {}
    for column in row.__table__.columns:
        value = getattr(row, column.name, None)
        if isinstance(value, Decimal):
            # Decimal is not JSON-encodable and float() would round money. The
            # string form is exact and parses back cleanly.
            value = str(value)
        elif isinstance(value, (datetime,)):
            value = value.isoformat()
        elif isinstance(value, uuid.UUID):
            value = str(value)
        out[column.name] = value
    return out