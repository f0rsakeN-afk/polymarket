#!/usr/bin/env python3
"""
Check every pool's escrow against what it still owes.

The same invariants the nightly Celery task (`audit_escrow_invariants`) runs,
but on demand and with human-readable output, so you can investigate one
market before going to production:

    ./scripts/audit_escrow.py                      # everything
    ./scripts/audit_escrow.py --market <uuid>      # one market, repeatedly
    ./scripts/audit_escrow.py --json               # machine-readable

Reports only. It never repairs a ledger: a repair written by something that
doesn't fully understand the drift is how a rounding bug becomes a loss.

Exit codes: 0 = clean, 1 = violations found, 2 = bad usage/unreachable.
"""
import argparse
import asyncio
import json
import os
import sys
from pathlib import Path

# Allow `python scripts/audit_escrow.py` from the repo without installing.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(Path(__file__).resolve().parents[1] / ".env")


async def _run(market_id: str | None, as_json: bool) -> int:
    from app.database import async_session
    from app.services.escrow_audit import audit_escrow_invariants

    session = async_session()
    try:
        violations = await audit_escrow_invariants(
            session, market_ids=[market_id] if market_id else None
        )
    finally:
        await session.close()

    if as_json:
        print(json.dumps([v.as_log() for v in violations], indent=2))
        return 1 if violations else 0

    if not violations:
        print("escrow audit clean: every pool covers its obligations")
        return 0

    print(f"{len(violations)} invariant violation(s):\n")
    for v in violations:
        print(f"  {v.market_slug}  ({v.market_id})")
        print(f"    kind:      {v.kind}")
        print(f"    detail:    {v.detail}")
        print(f"    owed:      {v.owed}")
        print(f"    available: {v.available}")
        print(f"    shortfall: {v.shortfall}")
        for k, val in v.extra.items():
            print(f"    {k}: {val}")
        print()
    print("These markets will refuse to settle until the escrow is funded.")
    print("Nothing was modified • this tool only reports.")
    return 1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[1])
    parser.add_argument("--market", help="audit a single market by UUID")
    parser.add_argument("--json", action="store_true", help="machine-readable output")
    args = parser.parse_args()

    url = os.environ.get("DATABASE_URL", "")
    if "localhost" not in url and url:
        print(f"note: auditing {url.split('@')[-1]}", file=sys.stderr)

    try:
        return asyncio.run(_run(args.market, args.json))
    except Exception as exc:  # noqa: BLE001 -- CLI boundary
        print(f"audit failed: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())