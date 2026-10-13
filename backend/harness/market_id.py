"""Print the id of a seeded market, by slug.

The browser tests need a market id to push realtime frames at, and CI has no
idea what it is because ids are generated. Hardcoding one works locally and then
breaks the first time the database is recreated - which is to say, it breaks in
CI, where nobody is watching, and the suite skips itself.

Resolving it from the database is the only thing that is actually true in both
places. Exits non-zero with a clear message rather than printing nothing, so a
missing market fails the run instead of quietly becoming a skipped suite.

    python -m harness.market_id bitcoin-100k-2024
"""

import asyncio
import sys

from sqlalchemy import select

from app.database import _get_async_session_maker
from app.models.market import Market


async def market_id(slug: str) -> str | None:
    maker = _get_async_session_maker()
    async with maker() as db:
        result = await db.execute(select(Market.id).where(Market.slug == slug))
        found = result.scalar_one_or_none()
        return str(found) if found else None


def main() -> int:
    if len(sys.argv) < 2:
        print("usage: python -m harness.market_id <slug>", file=sys.stderr)
        return 2

    slug = sys.argv[1]
    found = asyncio.run(market_id(slug))

    if not found:
        print(
            f"no market with slug {slug!r}. Run the seeder first:\n"
            "    python -m scripts.seed",
            file=sys.stderr,
        )
        return 1

    print(found)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())