"""Account lifecycle: see what we hold about you, and leave.

Two endpoints, and the pairing is the point.

**Export first, delete second.** A user who wants out of a product that holds
their money currently has to email support and wait - which is both a regulatory
exposure and a trust problem. The export is also the honest counterpart to the
deletion: one says what is kept and why, the other says what is erased. A
deletion that quietly dropped the ledger would be simple to implement and
indefensible, because the ledger is the market's shared history.

Erasion itself lives in `app.services.account_deletion`, where the reasoning
about what must be retained and why is written down rather than implied by
whichever tables happen to cascade.
"""

import logging

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.exceptions import ConflictError
from app.api.responses import success_response
from app.api.step_up import require_step_up
from app.database import get_db
from app.deps import get_current_user
from app.models.user import User
from app.schemas.auth import StepUpRequest
from app.services.account_deletion import (
    RETAINED_TABLES,
    AccountDeletionBlockedError,
    anonymise_account,
    export_account,
    outstanding_obligations,
)

logger = logging.getLogger("PredictX")
router = APIRouter(prefix="/account", tags=["account"])


@router.get("/export", summary="Export everything held about your account")
async def export_my_account(
    request: Request, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)
):
    """A machine-readable copy of every record we hold about this account.

    Deliberately complete rather than minimal. An export that quietly omits, say,
    the positions rows is worse than no export at all, because it invites the
    belief that it is the whole picture.
    """
    document = await export_account(db, user)
    logger.info(f"Account data exported: id={user.id}")

    # As an attachment, not a normal JSON body: a large export rendered inline in
    # a browser is a rendering hazard (a multi-megabyte string inside the SPA's
    # own error boundary), and `Content-Disposition` is what makes "save this"
    # work without the user having to select-all on a JSON blob.
    stamp = document["exported_at"][:10]
    return JSONResponse(
        content=document,
        headers={
            "Content-Disposition": f'attachment; filename="predictx-export-{stamp}.json"'
        },
    )


@router.get("/deletion-impact", summary="What would block account deletion")
async def deletion_impact(db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)):
    """Whether deletion would succeed right now, and why not if it wouldn't.

    A separate read-only endpoint rather than an error to discover by trying,
    because "cannot delete" is only actionable if the user is told *what* is in
    the way before they commit to the flow - and the flow ends in an irreversible
    erasure, which is the worst possible moment to introduce a new condition.
    """
    open_orders, unsettled = await outstanding_obligations(db, user.id)
    blocked = bool(open_orders or unsettled)
    return success_response(
        {
            "can_delete": not blocked,
            "open_orders": open_orders,
            "unsettled_positions": unsettled,
            "retained_even_after_deletion": list(RETAINED_TABLES),
            "blocked_detail": (
                AccountDeletionBlockedError(open_orders, unsettled).detail()
                if blocked
                else None
            ),
        }
    )


@router.delete("", summary="Delete your account")
async def delete_my_account(
    data: StepUpRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Erase this account.

    Requires step-up - the password, and a TOTP code when 2FA is enabled -
    because "delete my account" behind a bare session cookie is the kind of thing
    a session-riding attacker most wants, and the kind nobody could undo.

    **The identity is erased; the ledger is kept.** Trades, orders, positions,
    transactions, disputes, comments and referral rows stay, because they are
    either the market's shared history or an accounting obligation. What is
    removed is the person: email, username, password, 2FA secret, sessions,
    notifications, alerts and referral code.

    Refused outright when the account still holds or owes money - open orders
    have locked funds, and positions in unresolved markets have not yet paid out.
    Neither can be walked away from without stranding the other side.
    """
    await require_step_up(request, user, data)

    try:
        summary = await anonymise_account(db, user)
    except AccountDeletionBlockedError as exc:
        # 409 rather than 400: nothing about the request was malformed, and the
        # same payload will succeed later once the user closes their orders.
        raise ConflictError("Cannot delete account with outstanding obligations", exc.detail())

    logger.info(f"Account deleted: id={user.id}")
    return success_response(summary, message="Account deleted")