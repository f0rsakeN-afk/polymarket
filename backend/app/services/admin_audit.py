"""Audit trail for privileged actions.

The point of this module is narrow and blunt: **a privileged action that leaves
no record might as well not have an audit log at all.** Before it existed, an
admin could move accumulated protocol fees to the treasury, or approve a market
into tradability, and nothing recorded that it happened or who did it.

Two decisions worth stating, because both are about what an audit log has to be
able to answer.

**Failures are recorded too.** A rejected privileged action - an admin attempting
to ban the treasury account - is exactly the thing worth knowing about, and a log
that only holds successes is a log of what happened to be permitted.

**Recording never breaks the action.** A failure to write the audit row is logged
loudly and swallowed, because the alternative is that a logging fault prevents an
admin from acting - and an action refused because it could not be logged is an
action nobody can see was even attempted. The gap is surfaced through
`ADMIN_AUDIT_WRITE_FAILURES` rather than by taking the API down.
"""

import logging
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.middleware.metrics import ADMIN_AUDIT_WRITE_FAILURES
from app.models.audit import AdminAuditEvent

logger = logging.getLogger("PredictX")

# Action names. Kept as constants rather than inline strings because these become
# a contract: alert rules, exports and incident reviews all key off them, and a
# typo in one place is a gap nobody notices until they query for it.
MARKET_APPROVED = "market_approved"
MARKET_REJECTED = "market_rejected"
USER_BANNED = "user_banned"
USER_UNBANNED = "user_unbanned"
PROTOCOL_FEES_DISTRIBUTED = "protocol_fees_distributed"
# A *manual* withdrawal, as distinct from the protocol-fee sweep. Two action
# names rather than one, because "money moved" and "someone typed a number"
# are different events and an auditor needs to tell them apart.
TREASURY_DISTRIBUTION = "treasury_distribution"
# Reading the movement history. Not reading the balance - see the note in
# `app/api/treasury.py`: a balance view is a dashboard poll, and auditing every
# one of them floods the table with the least interesting rows in it.
TREASURY_LOG_VIEWED = "treasury_log_viewed"
# A privileged action refused because step-up credentials were wrong. Audited
# because an actor repeatedly guessing at them is itself worth a row.
STEP_UP_FAILED = "step_up_failed"
# A dispute ruling. An upheld ruling resolves the market and pays out, so this
# is the most consequential privileged action in the system - and it lives in
# `api/disputes.py`, not `api/admin.py`, which is why the original coverage
# sweep never saw it.
DISPUTE_ADJICATED = "dispute_adjudicated"
# An admin pulling a user's financial record. A read, so no step-up - there is no
# irreversible action - but "who looked at whose finances" is a question an
# operator must be able to answer, so it is recorded like the rest.
USER_RECORD_VIEWED = "user_record_viewed"


class AdminAuditService:
    @staticmethod
    async def log_action(
        db: AsyncSession,
        *,
        action: str,
        actor_id: str | None,
        actor_email: str | None,
        request=None,
        target_type: str | None = None,
        target_id: str | None = None,
        summary: str | None = None,
        payload: dict[str, Any] | None = None,
        success: bool = True,
        failure_reason: str | None = None,
    ) -> None:
        """Record one privileged action.

        `request` is optional and only used to capture the caller's IP and user
        agent. It is not required, so a privileged action taken from a background
        job or a script can still be attributed to whoever scheduled it.
        """
        ip_address = None
        user_agent = None
        if request is not None:
            try:
                from app.api.middleware import _get_real_client_ip

                ip_address = _get_real_client_ip(request)
            except Exception:
                ip_address = None
            try:
                user_agent = request.headers.get("user-agent")
            except Exception:
                user_agent = None

        row = AdminAuditEvent(
            actor_id=actor_id,
            actor_email=actor_email,
            action=action,
            target_type=target_type,
            target_id=target_id,
            summary=summary,
            # Amounts are Decimal; JSONB cannot hold them. Stringified rather than
            # float()-ed, because rounding a treasury figure to a binary float is
            # precisely the mistake an audit log must not introduce.
            payload={k: (str(v) if hasattr(v, "__float__") and not isinstance(v, (int, float)) else v)
                     for k, v in (payload or {}).items()},
            ip_address=ip_address,
            user_agent=user_agent,
            success="success" if success else "failure",
            failure_reason=failure_reason,
        )
        db.add(row)

        try:
            await db.commit()
        except Exception as exc:
            # Roll back so the failed audit write cannot poison the caller's
            # transaction, then surface it. The action itself is not undone - see
            # the module docstring for why.
            await db.rollback()
            ADMIN_AUDIT_WRITE_FAILURES.inc()
            logger.error(
                f"ADMIN AUDIT WRITE FAILED for {action} by {actor_email or actor_id}: {exc}. "
                "The action was performed but is NOT recorded.",
                exc_info=True,
            )