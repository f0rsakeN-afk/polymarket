import logging
from decimal import Decimal

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.exceptions import ForbiddenError, UnauthorizedError, ValidationError
from app.api.responses import PaginatedResponse, success_response
from app.api.step_up import require_step_up
from app.database import get_db, get_db_replica
from app.deps import get_current_user
from app.models.treasury import Treasury, TreasuryLog
from app.models.user import User
from app.schemas.treasury import (
    TreasuryDistributeRequest,
    TreasuryLogResponse,
    TreasuryResponse,
)
from app.services import admin_audit
from app.services.admin_audit import AdminAuditService

logger = logging.getLogger("PredictX")
router = APIRouter(prefix="/treasury", tags=["treasury"])


async def _get_or_create_treasury(db: AsyncSession) -> Treasury:
    """Get or create the singleton treasury row.

    Uses INSERT ... ON CONFLICT DO NOTHING to eliminate the race condition
    between SELECT and INSERT that existed in the previous implementation.
    """
    # `on_conflict_do_nothing` is PostgreSQL dialect API • importing `insert`
    # from sqlalchemy gives a generic Insert that doesn't have it (AttributeError
    # at runtime, i.e. 500 on the distribute path).
    from sqlalchemy.dialects.postgresql import insert

    # Try INSERT directly • if singleton row already exists, conflict is ignored.
    await db.execute(
        insert(Treasury).values(singleton=True).on_conflict_do_nothing(index_elements=["singleton"])
    )
    # Always re-read: either we just inserted it or it already existed.
    result = await db.execute(select(Treasury).limit(1))
    treasury = result.scalar_one_or_none()
    if not treasury:
        raise RuntimeError("Failed to create treasury singleton")
    await db.refresh(treasury)
    return treasury


@router.get("")
async def get_treasury(
    request: Request,
    db: AsyncSession = Depends(get_db_replica),
):
    # Admin-only: treasury balance and fee totals are operational financial
    # data • the same privilege boundary as POST /treasury/distribute.
    await _get_admin_user(request, db)

    # Read must be side-effect free. The singleton row is created by the
    # write path (distribute), so a fresh install simply reports zeros here
    # instead of INSERTing on a GET.
    result = await db.execute(select(Treasury).limit(1))
    treasury = result.scalar_one_or_none()
    if treasury is None:
        return success_response(TreasuryResponse(
            id="",
            balance="0",
            total_fees_collected="0",
            total_fees_distributed="0",
        ))
    return success_response(TreasuryResponse(
        id=str(treasury.id),
        balance=str(treasury.balance),
        total_fees_collected=str(treasury.total_fees_collected),
        total_fees_distributed=str(treasury.total_fees_distributed),
    ))


@router.get("/logs")
async def get_treasury_logs(
    request: Request,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    event: str | None = Query(None, max_length=64),
    db: AsyncSession = Depends(get_db_replica),
    audit_db: AsyncSession = Depends(get_db),
):
    """The movement history, and who asked for it.

    ## Why this read is audited and the balance read is not

    This one is the audit trail of money movements: who withdrew, how much, and
    what reference it carried. An admin reading it is precisely the event a
    reviewer wants in the record — it is how a disputed balance gets explained
    after the fact.

    `GET /treasury` is deliberately left alone. It returns a single row that
    every dashboard polls; recording each one would bury the interesting rows
    under thousands of balance checks, which is the same reasoning that keeps
    the dispute *list* unaudited while its detail is.

    ## Why a second session

    `db` is the replica, and it exists to be read from. The audit row is a write,
    so it goes to the primary through `audit_db` - writing through a replica is
    either refused or silently discarded depending on the deployment, and a
    silently discarded audit row is worse than none, because it looks recorded.
    """
    admin = await _get_admin_user(request, db)

    await AdminAuditService.log_action(
        audit_db,
        action=admin_audit.TREASURY_LOG_VIEWED,
        actor_id=str(admin.id),
        actor_email=admin.email,
        request=request,
        target_type="treasury",
        summary="Treasury movement history viewed",
        payload={"page": page, "page_size": page_size, "event": event},
    )

    result = await db.execute(select(Treasury).limit(1))
    treasury = result.scalar_one_or_none()
    if treasury is None:
        return PaginatedResponse(data=[], total=0, page=page, page_size=page_size, has_more=False)

    query = select(TreasuryLog).where(TreasuryLog.treasury_id == treasury.id)
    if event:
        query = query.where(TreasuryLog.event == event)
    query = query.order_by(TreasuryLog.created_at.desc()).offset((page - 1) * page_size).limit(page_size)

    result = await db.execute(query)
    logs = result.scalars().all()

    count_query = select(func.count()).select_from(TreasuryLog).where(TreasuryLog.treasury_id == treasury.id)
    if event:
        count_query = count_query.where(TreasuryLog.event == event)
    total_result = await db.execute(count_query)
    total = total_result.scalar() or 0

    return PaginatedResponse(
        data=[
            TreasuryLogResponse(
                id=str(log_entry.id),
                event=log_entry.event,
                amount=str(log_entry.amount),
                reference_type=log_entry.reference_type,
                reference_id=log_entry.reference_id,
                created_at=log_entry.created_at,
            )
            for log_entry in logs
        ],
        total=total,
        page=page,
        page_size=page_size,
        has_more=(page * page_size) < total,
    )


async def _get_admin_user(request: Request, db: AsyncSession = Depends(get_db)) -> User:
    """Require current user to be admin."""
    user = await get_current_user(request, db)
    if not user.is_admin:
        raise ForbiddenError("Admin access required")
    return user


@router.post("/distribute")
async def distribute_fees(
    # `data` before `amount`: a parameter with a default cannot precede one
    # without. `amount` stays a query parameter because that is where it already
    # lived, and moving it would be a gratuitous breaking change for a caller.
    #
    # Optional at the wire level and required inside the handler, so that the
    # admin check runs first. See the comment where `data` is used.
    data: TreasuryDistributeRequest | None = None,
    amount: Decimal = Query(..., gt=0, le=100_000_000, description="Amount to distribute (must be positive, max 100M)"),
    request: Request = None,
    db: AsyncSession = Depends(get_db),
):
    """Withdraw an amount from the treasury, by hand.

    ## Why this now costs a step-up and writes an audit row

    It did neither. It was admin-gated, adjusted `treasury.balance`, wrote a
    `TreasuryLog` — and stopped there. So:

    - **An admin session was sufficient.** Every other operation that moves money
      (`/admin/distribute-protocol-fees`, dispute adjudication) requires step-up,
      on the grounds that an admin session is a bearer token. This one was the
      exception, and it was the exception that withdrew funds.
    - **The audit trail could not say who did it.** A `TreasuryLog` records the
      amount, so the movement is traceable — but not the actor. A disputed balance
      had a number and no name next to it, which is the exact gap
      `distribute-protocol-fees` was fixed for and this endpoint was missed on.

    Both gaps are closed here rather than by deleting the endpoint: withdrawing a
    specific amount is a real operation distinct from the protocol-fee sweep, and
    removing capability because it was under-protected is a worse answer than
    protecting it.
    """
    admin = await _get_admin_user(request, db)

    # The body is validated *here*, after the admin check, rather than as a typed
    # FastAPI parameter — which would run before the handler and turn every
    # non-admin's 403 into a 422.
    #
    # That is not a cosmetic difference. 422 tells an unauthorized caller the
    # shape of a privileged endpoint's contract, and it is the wrong answer to the
    # question they asked: authorisation is decided first, and "no" must not
    # arrive dressed as "your request was malformed".
    if data is None:
        raise ValidationError(
            "This withdrawal requires step-up credentials: send "
            "{password, totp_code} to confirm.",
            error_code="STEP_UP_REQUIRED",
        )

    try:
        await require_step_up(request, admin, data)
    except (UnauthorizedError, ValidationError) as exc:
        # A refused step-up is itself worth recording: an actor repeatedly probing
        # a money-moving endpoint is the thing an auditor wants to see.
        await AdminAuditService.log_action(
            db,
            action=admin_audit.TREASURY_DISTRIBUTION,
            actor_id=str(admin.id),
            actor_email=admin.email,
            request=request,
            target_type="treasury",
            summary="Step-up failed before a treasury withdrawal",
            success=False,
            failure_reason=str(exc)[:255],
        )
        raise

    treasury = await _get_or_create_treasury(db)
    amount_dec = amount
    if treasury.balance < amount_dec:
        raise ValidationError("Insufficient treasury balance")

    treasury.balance -= amount_dec
    treasury.total_fees_distributed += amount_dec

    log = TreasuryLog(
        treasury_id=treasury.id,
        event="distribution",
        amount=amount_dec,
        reference_type="manual",
    )
    db.add(log)

    # The actor is recorded *in the same transaction as the money*. Auditing
    # after the commit would leave a window where the balance moved and the trail
    # does not, which is the window an auditor would be looking in.
    await AdminAuditService.log_action(
        db,
        action=admin_audit.TREASURY_DISTRIBUTION,
        actor_id=str(admin.id),
        actor_email=admin.email,
        request=request,
        target_type="treasury",
        target_id=str(treasury.id),
        summary=f"Withdrew {amount_dec} from treasury",
        success=True,
        payload={"amount": str(amount_dec), "event": "manual_withdrawal"},
    )
    await db.commit()

    return success_response(
        {"message": f"Distributed {amount} from treasury", "amount": str(amount_dec)},
        message=f"Distributed {amount} from treasury",
    )
